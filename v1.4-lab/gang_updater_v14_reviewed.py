"""GANG V1.4 isolated signed updater. Python >=3.10; pip install cryptography.

Safety: never run this against a production scanner. Installation requires a
separate, explicitly marked isolated lab directory and test_mode=true.
"""
import argparse
import base64
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FILES = frozenset({'gang_trader.py', 'market_sources.py', 'test_official_api.py', 'test_sources_fix.py'})
REQUIRED = frozenset({'gang_trader.py', 'market_sources.py'})
MAX_ZIP = 4_000_000
MAX_FILE = 2_000_000
MAX_UNCOMPRESSED = 4_000_000


def atomic_write(path, data):
    path = pathlib.Path(path)
    temp = path.with_name(path.name + '.tmp')
    try:
        with open(temp, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def download(url, ca_cert=None):
    if not isinstance(url, str) or not url.startswith('https://'):
        raise ValueError('Only HTTPS URLs allowed')
    ctx = ssl.create_default_context(cafile=ca_cert) if ca_cert else ssl.create_default_context()
    req = urllib.request.Request(url, headers={'User-Agent': 'GANG-Updater/1.4'})
    # Reject redirects to non-HTTPS destinations, including HTTP downgrade.
    class HttpsRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            if not newurl.startswith('https://'):
                raise ValueError('HTTPS redirect downgrade rejected')
            return super().redirect_request(request, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(HttpsRedirect(), urllib.request.HTTPSHandler(context=ctx))
    with opener.open(req, timeout=15) as resp:
        payload = resp.read(MAX_ZIP + 1)
    if len(payload) > MAX_ZIP:
        raise ValueError('download too large')
    return payload


def verify_manifest(manifest, key_b64):
    if not isinstance(manifest, dict):
        raise ValueError('manifest must be object')
    signature = base64.b64decode(manifest['signature'], validate=True)
    pub = base64.b64decode(key_b64, validate=True)
    unsigned = {k: v for k, v in manifest.items() if k != 'signature'}
    Ed25519PublicKey.from_public_bytes(pub).verify(signature, canonical(unsigned))
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,48}', str(manifest['version'])):
        raise ValueError('unsafe version')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', str(manifest['sha256'])):
        raise ValueError('bad sha256')
    if not isinstance(manifest.get('zip_url'), str) or not manifest['zip_url'].startswith('https://'):
        raise ValueError('ZIP URL must be HTTPS')
    return unsigned


def safe_stage(raw, stage):
    stage = pathlib.Path(stage)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names = set()
        total = 0
        for info in z.infolist():
            if info.is_dir():
                raise ValueError('directory entry not permitted')
            name = pathlib.PurePosixPath(info.filename)
            # Exact string match prevents ./, backslash, absolute and traversal names.
            if info.filename not in FILES or len(name.parts) != 1 or info.filename in names:
                raise ValueError('unexpected or duplicate zip entry: ' + info.filename)
            mode = (info.external_attr >> 16) & 0o170000
            if mode not in (0, 0o100000):
                raise ValueError('non-regular ZIP entry')
            if info.file_size > MAX_FILE:
                raise ValueError('oversize entry')
            total += info.file_size
            if total > MAX_UNCOMPRESSED:
                raise ValueError('uncompressed archive too large')
            names.add(info.filename)
            content = z.read(info)
            if len(content) != info.file_size:
                raise ValueError('ZIP size mismatch')
            (stage / info.filename).write_bytes(content)
    if not REQUIRED.issubset(names):
        raise ValueError('required modules missing')


def health(root):
    # Compile into a temp cache outside the installation root to avoid creating
    # __pycache__ inside an installation. This is a syntax check, not execution.
    for name in REQUIRED:
        source = (root / name).read_bytes()
        compile(source, str(root / name), 'exec')
    # Explicitly executing the candidate is only allowed in a throwaway lab.
    result = subprocess.run([sys.executable, '-I', str(root / 'gang_trader.py'), '--test'],
                            cwd=root, capture_output=True, text=True, timeout=30,
                            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode:
        raise RuntimeError('health check failed: ' + (result.stdout + result.stderr)[-500:])
    return result.stdout.strip()[-300:]


def validate_root(root):
    original_root = pathlib.Path(root).absolute()
    if original_root.is_symlink():
        raise ValueError('symlink root rejected')
    root = original_root.resolve(strict=True)
    if not root.is_dir() or root.is_symlink():
        raise ValueError('invalid root')
    cfg_path = root / 'update_config_v14.json'
    marker = root / '.gang_v14_isolated'
    if not cfg_path.is_file() or cfg_path.is_symlink() or not marker.is_file() or marker.is_symlink():
        raise ValueError('isolated config/marker missing or linked')
    cfg = read_json(cfg_path)
    if cfg.get('install_root_id') != 'GANG_V14_ISOLATED' or cfg.get('test_mode') is not True:
        raise ValueError('isolated lab guard missing')
    for name in FILES:
        path = root / name
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError('unsafe target: ' + name)
    backup_root = root / 'backups'
    if backup_root.is_symlink() or (backup_root.exists() and not backup_root.is_dir()):
        raise ValueError('unsafe backup directory')
    return root, cfg_path, cfg


def check(root, config=None, dry_run=False, fetch=None, runner=None):
    # fetch and runner are optional dependency injection points for isolated tests.
    root, cfg_path, cfg = validate_root(root)
    if not cfg.get('enabled', False):
        return 'DISABLED'
    if not cfg.get('public_key_ed25519') or not cfg.get('manifest_url'):
        raise ValueError('manifest URL or pinned public key missing')
    ca = cfg.get('test_ca_cert')
    if ca and not cfg['manifest_url'].startswith('https://localhost:'):
        raise ValueError('custom CA restricted to localhost')
    get = fetch or download
    manifest = json.loads(get(cfg['manifest_url'], ca))
    verify_manifest(manifest, cfg['public_key_ed25519'])
    old = str(cfg['version'])
    new = str(manifest['version'])
    if new == old:
        return 'UP_TO_DATE ' + old
    # Reject signed replay/downgrade. Non-numeric versions cannot be safely ordered.
    version_pattern = r'[0-9]+(?:\.[0-9]+)*'
    if not re.fullmatch(version_pattern, old) or not re.fullmatch(version_pattern, new):
        raise ValueError('unorderable version; manual review required')
    def version_parts(v):
        return tuple(int(x) for x in v.split('.'))
    if version_parts(new) <= version_parts(old):
        raise ValueError('version rollback/replay rejected')
    if ca and not manifest['zip_url'].startswith('https://localhost:'):
        raise ValueError('test ZIP must be localhost')
    raw = get(manifest['zip_url'], ca)
    if hashlib.sha256(raw).hexdigest().lower() != manifest['sha256'].lower():
        raise ValueError('SHA256 mismatch')
    with tempfile.TemporaryDirectory(prefix='gang_v14_stage_') as temp:
        stage = pathlib.Path(temp)
        safe_stage(raw, stage)
        run_health = runner or health
        run_health(stage)
        if dry_run:
            return 'DRY_RUN_VALID ' + new
        # Installation is *only* supported for explicitly isolated test roots.
        # Refuse any target that is already being used by a scanner via lock marker.
        if (root / '.scanner_running').exists():
            return 'VERIFIED_PENDING_MAINTENANCE ' + new
        backup = root / 'backups' / ('before_' + new + '_' + str(time.time_ns()))
        backup.mkdir(parents=True, exist_ok=False)
        originals = {name: (root / name).exists() for name in FILES}
        # Complete the backup before any installation write. Backup failures
        # leave the original installation untouched.
        for name, exists in originals.items():
            if exists:
                shutil.copy2(root / name, backup / name)
        shutil.copy2(cfg_path, backup / 'update_config_v14.json')
        try:
            for name in FILES:
                if (stage / name).exists():
                    atomic_write(root / name, (stage / name).read_bytes())
            run_health(root)
            cfg['version'] = new
            atomic_write(cfg_path, (json.dumps(cfg, ensure_ascii=False, indent=2) + '\n').encode())
            return 'UPDATED ' + old + ' -> ' + new + ' backup=' + str(backup)
        except BaseException:
            for name, exists in originals.items():
                if exists:
                    atomic_write(root / name, (backup / name).read_bytes())
                elif (root / name).exists():
                    (root / name).unlink()
            atomic_write(cfg_path, (backup / 'update_config_v14.json').read_bytes())
            run_health(root)
            raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--interval-seconds', type=float, default=0)
    parser.add_argument('--cycles', type=int, default=1)
    args = parser.parse_args()
    if args.cycles < 1 or not 0 <= args.interval_seconds < float('inf'):
        parser.error('invalid schedule')
    for i in range(args.cycles):
        try:
            print(check(args.root, dry_run=args.dry_run), flush=True)
        except Exception as e:
            print('UPDATE_REJECTED ' + type(e).__name__ + ': ' + str(e), flush=True)
            if args.cycles == 1:
                return 1
        if i + 1 < args.cycles:
            time.sleep(args.interval_seconds)
    return 0


if __name__ == '__main__':
    sys.exit(main())
