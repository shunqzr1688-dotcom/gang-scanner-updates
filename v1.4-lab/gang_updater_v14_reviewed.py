"""Offline signed, transactional updater for disposable V1.4 laboratories only.

Never pass a production directory. No network client and no candidate execution.
Windows directory/power-loss durability requires separate physical-machine tests.
"""
import argparse
import ast
import base64
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import sys
import time
import uuid
import zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FILES = ('gang_trader.py', 'market_sources.py', 'test_official_api.py', 'test_sources_fix.py')
CONFIG = 'update_config_v14.json'
MARKER = '.gang_v14_isolated'
MAX_ZIP = 4_000_000
MAX_FILE = 2_000_000
MAX_TOTAL = 4_000_000


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    if len(raw) > MAX_FILE:
        raise ValueError('JSON too large')
    return json.loads(raw, object_pairs_hook=unique)


def plain(path, directory=False):
    """Refuse symlinks, Windows reparse points and hardlinked files."""
    path = Path(path)
    if not os.path.lexists(path):
        return
    s = path.lstat()
    if stat.S_ISLNK(s.st_mode) or getattr(s, 'st_file_attributes', 0) & 0x400:
        raise ValueError('linked/reparse path: ' + path.name)
    if directory:
        if not stat.S_ISDIR(s.st_mode):
            raise ValueError('directory required')
    elif not stat.S_ISREG(s.st_mode) or s.st_nlink != 1:
        raise ValueError('plain unlinked file required: ' + path.name)


def sync_dir(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    # Python has no portable directory fsync on Windows. Do not claim power-loss
    # durability there without NTFS / hardware acceptance results.


def atomic_write(path, data):
    path = Path(path)
    plain(path)
    tmp = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with open(tmp, 'xb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        if (path.parent / MARKER).is_file():
            checkpoint(path.parent, "atomic_fsync:" + path.name)
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if tmp.exists():
            tmp.unlink()


def validate_root(root):
    root = Path(os.path.abspath(root))
    for p in reversed((root, *root.parents)):
        plain(p, directory=True)
    if not root.is_dir():
        raise ValueError('root missing')
    for name in (MARKER, CONFIG):
        plain(root / name)
        if not (root / name).is_file():
            raise ValueError('isolated marker/config required')
    if (root / MARKER).read_bytes() != b'GANG_V14_DISPOSABLE_LAB\n':
        raise ValueError('invalid lab marker')
    cfg = read_json(root / CONFIG)
    if cfg.get('install_root_id') != 'GANG_V14_ISOLATED' or cfg.get('test_mode') is not True:
        raise ValueError('isolated lab guard missing')
    version(cfg['version'])
    for name in (*FILES, '.update.lock', '.transaction.json', '.scanner_running'):
        plain(root / name)
    plain(root / '.transactions', directory=True)
    if os.path.lexists(root / '.scanner_running'):
        raise RuntimeError('scanner running; refusing mutation or recovery')
    return root, cfg


@contextmanager
def locked(root, timeout=5):
    path = root / '.update.lock'
    plain(path)
    # Persistent lock inode: never unlink, which could split concurrent locks.
    with open(path, 'a+b') as f:
        f.seek(0, os.SEEK_END)
        if f.tell() == 0:
            f.write(b'0')
            f.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    f.seek(0)
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('updater lock busy')
                time.sleep(.02)
        try:
            yield
        finally:
            if os.name == 'nt':
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def version(v):
    if not isinstance(v, str) or not re.fullmatch(r'(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})\.(0|[1-9][0-9]{0,5})', v):
        raise ValueError('strict three-part version required')
    return tuple(map(int, v.split('.')))


def static_check(raw, name):
    tree = ast.parse(raw, filename=name)
    compile(tree, name, 'exec')
    # Conservative lab allowlist, not a security sandbox or malicious-code proof.
    allowed = {'json', 'decimal', 'math', 'dataclasses', 'typing', 'gang_trader', 'market_sources'}
    forbidden = {'eval', 'exec', 'compile', '__import__', 'open', 'getattr', 'setattr', 'globals', 'locals', 'breakpoint', 'input'}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            if any(a.name.split('.')[0] not in allowed for a in n.names):
                raise ValueError('static policy: import denied in ' + name)
        if isinstance(n, ast.ImportFrom):
            if n.level or (n.module or '').split('.')[0] not in allowed:
                raise ValueError('static policy: import denied in ' + name)
        if isinstance(n, ast.Name) and (n.id in forbidden or n.id.startswith('__')):
            raise ValueError('static policy: dynamic access denied')
        if isinstance(n, ast.Attribute) and n.attr.startswith('__'):
            raise ValueError('static policy: dunder access denied')
    return tree


def verify_package(manifest, raw, key):
    if not isinstance(manifest, dict) or set(manifest) != {'schema', 'version', 'sha256', 'files', 'signature'}:
        raise ValueError('manifest schema fields invalid')
    unsigned = {k: v for k, v in manifest.items() if k != 'signature'}
    Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True)).verify(
        base64.b64decode(manifest['signature'], validate=True), canonical(unsigned))
    if type(manifest['schema']) is not int or manifest['schema'] != 1:
        raise ValueError('unsupported schema')
    version(manifest['version'])
    hashes = manifest['files']
    if not isinstance(hashes, dict) or set(hashes) != set(FILES):
        raise ValueError('complete four-module package required')
    for h in [manifest['sha256'], *hashes.values()]:
        if not isinstance(h, str) or not re.fullmatch('[a-f0-9]{64}', h):
            raise ValueError('invalid SHA256')
    if len(raw) > MAX_ZIP or digest(raw) != manifest['sha256']:
        raise ValueError('archive SHA256/size mismatch')
    contents = {}
    total = 0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.infolist()) != len(FILES):
            raise ValueError('archive entry count invalid')
        for info in z.infolist():
            mode = (info.external_attr >> 16) & 0o170000
            if info.filename not in FILES or info.filename in contents or info.is_dir():
                raise ValueError('unsafe/duplicate ZIP name')
            if mode not in (0, stat.S_IFREG) or info.flag_bits & 1:
                raise ValueError('nonregular/encrypted entry')
            total += info.file_size
            if info.file_size > MAX_FILE or total > MAX_TOTAL:
                raise ValueError('uncompressed size exceeded')
            content = z.read(info)
            if len(content) != info.file_size or digest(content) != hashes[info.filename]:
                raise ValueError('module SHA256 mismatch')
            static_check(content, info.filename)
            contents[info.filename] = content
    return contents


def checkpoint(root, point):
    """Fault injection is only reachable after disposable-root validation."""
    if os.environ.get('GANG_LAB_FAIL_AT') == point:
        raise RuntimeError('injected failure: ' + point)
    if os.environ.get('GANG_LAB_CRASH_AT') == point:
        os._exit(91)
    if os.environ.get('GANG_LAB_PAUSE_AT') == point:
        # Harness waits on this marker and kills this process, not a scanner.
        atomic_write(root / '.fault-ready', point.encode())
        while True:
            time.sleep(.05)


def load_journal(root):
    path = root / '.transaction.json'
    plain(path)
    if not path.exists():
        return None
    j = read_json(path)
    if set(j) != {'schema', 'id', 'state', 'backup', 'target'} or j['schema'] != 1:
        raise ValueError('invalid transaction journal')
    if not re.fullmatch('[a-f0-9]{32}', j['id']) or j['state'] not in {'PREPARED', 'APPLYING', 'COMMITTED', 'ROLLED_BACK'}:
        raise ValueError('invalid transaction identity/state')
    if set(j['backup']) != {*FILES, CONFIG} or set(j['target']) != {*FILES, CONFIG}:
        raise ValueError('invalid journal file set')
    if j['backup'][CONFIG] is None or any(h is None for h in j['target'].values()):
        raise ValueError('required journal hashes missing')
    for group in ('backup', 'target'):
        for h in j[group].values():
            if h is not None and (not isinstance(h, str) or not re.fullmatch('[a-f0-9]{64}', h)):
                raise ValueError('invalid journal hash')
    return j


def save_journal(root, j):
    atomic_write(root / '.transaction.json', canonical(j))


def verify_targets(root, hashes):
    for name, h in hashes.items():
        p = root / name
        plain(p)
        if h is None:
            if p.exists():
                raise ValueError('unexpected target: ' + name)
        elif not p.is_file() or digest(p.read_bytes()) != h:
            raise ValueError('target SHA256 mismatch: ' + name)


def restore(root, j):
    backup = root / '.transactions' / j['id']
    plain(root / '.transactions', directory=True)
    plain(backup, directory=True)
    # Check *all* backups before modifying even one target.
    verify_targets(backup, j['backup'])
    for name, h in j['backup'].items():
        p = root / name
        plain(p)
        if h is None:
            if p.exists():
                p.unlink()
                sync_dir(root)
        else:
            atomic_write(p, (backup / name).read_bytes())
        checkpoint(root, 'restore:' + name)
    verify_targets(root, j['backup'])
    j['state'] = 'ROLLED_BACK'
    save_journal(root, j)


def recover_locked(root):
    j = load_journal(root)
    if j is None:
        return 'CLEAN'
    if j['state'] in {'PREPARED', 'APPLYING'}:
        restore(root, j)
        return 'RECOVERED'
    verify_targets(root, j['target'] if j['state'] == 'COMMITTED' else j['backup'])
    return j['state']


def recover(root):
    root, _ = validate_root(root)
    with locked(root):
        validate_root(root)
        return recover_locked(root)


def install(root, manifest_path, package_path, dry_run=False):
    root, _ = validate_root(root)
    with locked(root):
        root, cfg = validate_root(root)
        recover_locked(root)
        cfg = read_json(root / CONFIG)
        if cfg.get('enabled') is not True:
            return 'DISABLED'
        manifest = read_json(manifest_path)
        # Bounded read, including untrusted local packages.
        with open(package_path, 'rb') as f:
            raw = f.read(MAX_ZIP + 1)
        contents = verify_package(manifest, raw, cfg['public_key_ed25519'])
        old, new = version(cfg['version']), version(manifest['version'])
        if new <= old:
            raise ValueError('version rollback/replay rejected')
        if dry_run:
            return 'DRY_RUN_VALID'
        cfg['version'] = manifest['version']
        contents[CONFIG] = canonical(cfg) + b'\n'
        txroot = root / '.transactions'
        txroot.mkdir(exist_ok=True)
        sync_dir(root)
        txid = uuid.uuid4().hex
        backup = txroot / txid
        backup.mkdir()
        sync_dir(txroot)
        hashes = {}
        for name in (*FILES, CONFIG):
            p = root / name
            plain(p)
            if p.exists():
                data = p.read_bytes()
                atomic_write(backup / name, data)
                hashes[name] = digest(data)
            else:
                hashes[name] = None
        verify_targets(backup, hashes)
        checkpoint(root, 'backup_ready')
        j = {'schema': 1, 'id': txid, 'state': 'PREPARED', 'backup': hashes,
             'target': {name: digest(data) for name, data in contents.items()}}
        save_journal(root, j)
        try:
            checkpoint(root, 'prepared')
            j['state'] = 'APPLYING'
            save_journal(root, j)
            checkpoint(root, 'applying')
            for name in (*FILES, CONFIG):
                atomic_write(root / name, contents[name])
                checkpoint(root, 'write:' + name)
            verify_targets(root, j['target'])
            checkpoint(root, 'before_commit')
            j['state'] = 'COMMITTED'
            save_journal(root, j)
            checkpoint(root, 'committed')
        except BaseException:
            # A durable COMMITTED record is authoritative, including if a
            # caller interrupts immediately after committing.
            persisted = load_journal(root)
            if persisted['state'] != 'COMMITTED':
                restore(root, persisted)
            raise
        return 'UPDATED'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True)
    p.add_argument('--manifest')
    p.add_argument('--package')
    p.add_argument('--recover', action='store_true')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    try:
        if a.recover:
            print(recover(a.root))
        else:
            if not a.manifest or not a.package:
                p.error('--manifest and --package required')
            print(install(a.root, a.manifest, a.package, a.dry_run))
        return 0
    except Exception as e:
        print('UPDATE_REJECTED ' + type(e).__name__ + ': ' + str(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
