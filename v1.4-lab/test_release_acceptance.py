"""Only generated mock modules/state in disposable directories; never real accounts.
Run: python test_release_acceptance.py --report <new report path>
"""
import argparse
import base64
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import gang_updater_v14_reviewed as u

SCRIPT = Path(u.__file__).resolve()
OLD = b'BUILD = "old"\n'
BUSINESS = b'''from decimal import Decimal
BUILD = "new"
def trade(state, side, quantity, price):
    quantity, price = Decimal(str(quantity)), Decimal(str(price))
    if side not in ("buy", "sell") or quantity <= 0 or price <= 0:
        raise ValueError("invalid order")
    cash, position = Decimal(state["cash"]), Decimal(state["position"])
    if side == "buy":
        if cash < quantity * price: raise ValueError("insufficient cash")
        cash -= quantity * price
        position += quantity
    else:
        if position < quantity: raise ValueError("insufficient position")
        cash += quantity * price
        position -= quantity
    return {"cash": str(cash), "position": str(position),
            "records": state["records"] + [{"side": side, "quantity": str(quantity), "price": str(price)}]}
'''


def make_zip(contents):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in contents.items():
            z.writestr(name, data)
    return b.getvalue()


class Lab:
    def __init__(self, base):
        self.base = Path(base)
        self.root = self.base / 'disposable-lab'
        self.root.mkdir()
        self.key = Ed25519PrivateKey.generate()
        public = self.key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.cfg = {'version': '1.3.2', 'enabled': True, 'test_mode': True,
                    'install_root_id': 'GANG_V14_ISOLATED', 'public_key_ed25519': base64.b64encode(public).decode()}
        (self.root / u.MARKER).write_bytes(b'GANG_V14_DISPOSABLE_LAB\n')
        (self.root / u.CONFIG).write_bytes(u.canonical(self.cfg))
        for name in u.FILES:
            (self.root / name).write_bytes(OLD)
        # Entirely synthetic, no account identifiers or credentials.
        state = {'cash': '10000.00', 'position': '3', 'records': [{'side': 'fixture'}]}
        for name in ('positions.mock.json', 'trades.mock.json', 'account.mock.json'):
            (self.root / name).write_bytes(u.canonical(state))
        self.outside = self.base / 'outside-sentinel.bin'
        self.outside.write_bytes(b'NEVER MODIFY')
        self.contents = {n: BUSINESS if n == 'gang_trader.py' else b'BUILD = "new"\n' for n in u.FILES}
        self.manifest = self.base / 'signed-manifest.json'
        self.package = self.base / 'candidate.zip'
        self.sign()
        self.before = self.snapshot()
        self.protected = self.protected_snapshot()

    def sign(self, raw=None, **fields):
        raw = make_zip(self.contents) if raw is None else raw
        self.package.write_bytes(raw)
        m = {'schema': 1, 'version': '1.4.0', 'sha256': u.digest(raw),
             'files': {n: u.digest(d) for n, d in self.contents.items()}}
        m.update(fields)
        self.m = m
        self.resign()

    def resign(self):
        m = dict(self.m)
        m['signature'] = base64.b64encode(self.key.sign(u.canonical(m))).decode()
        self.manifest.write_bytes(u.canonical(m))

    def snapshot(self):
        return {n: (self.root / n).read_bytes() if (self.root / n).exists() else None for n in (*u.FILES, u.CONFIG)}

    def protected_snapshot(self):
        return {str(p): u.digest(p.read_bytes()) for p in [self.outside, *self.root.glob('*.mock.json')]}

    def install(self, **kw):
        return u.install(self.root, self.manifest, self.package, **kw)

    def command(self, recovery=False):
        cmd = [sys.executable, str(SCRIPT), '--root', str(self.root)]
        return cmd + (['--recover'] if recovery else ['--manifest', str(self.manifest), '--package', str(self.package)])

    def env(self, **kw):
        # Remove all inherited account/cloud credentials from child processes.
        env = {k: v for k, v in os.environ.items() if k in ('PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR', 'LANG', 'LC_ALL')}
        env.update(kw)
        return env

    def child(self, recovery=False, **env):
        return subprocess.run(self.command(recovery), env=self.env(**env), capture_output=True, text=True, timeout=20)


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gang_v14_ACCEPTANCE_')
        self.addCleanup(self.tmp.cleanup)
        self.lab = Lab(self.tmp.name)
        self.addCleanup(self.check_protected)

    def check_protected(self):
        self.assertEqual(self.lab.protected, self.lab.protected_snapshot())

    def assert_old(self, lab=None):
        lab = lab or self.lab
        self.assertEqual(lab.before, lab.snapshot())

    def assert_new(self, lab=None):
        lab = lab or self.lab
        for name, data in lab.contents.items():
            self.assertEqual(data, (lab.root / name).read_bytes())
        self.assertEqual(u.read_json(lab.root / u.CONFIG)['version'], '1.4.0')

    def test_full_install_and_idempotent_recovery(self):
        self.assertEqual(self.lab.install(), 'UPDATED')
        self.assert_new()
        for _ in range(3):
            self.assertEqual(u.recover(self.lab.root), 'COMMITTED')
        self.assert_new()

    def test_dry_run(self):
        self.assertEqual(self.lab.install(dry_run=True), 'DRY_RUN_VALID')
        self.assert_old()
        self.assertFalse((self.lab.root / '.transaction.json').exists())

    def test_disabled(self):
        cfg = self.lab.cfg | {'enabled': False}
        (self.lab.root / u.CONFIG).write_bytes(u.canonical(cfg))
        self.assertEqual(self.lab.install(), 'DISABLED')

    def test_signature_tampering(self):
        m = u.read_json(self.lab.manifest)
        m['version'] = '1.5.0'
        self.lab.manifest.write_bytes(u.canonical(m))
        with self.assertRaises(Exception): self.lab.install()
        self.assert_old()

    def test_wrong_pinned_key(self):
        self.lab.key = Ed25519PrivateKey.generate()
        self.lab.resign()
        with self.assertRaises(Exception): self.lab.install()
        self.assert_old()

    def test_zip_hash_tampering(self):
        self.lab.package.write_bytes(self.lab.package.read_bytes() + b'tamper')
        with self.assertRaisesRegex(ValueError, 'SHA256'): self.lab.install()
        self.assert_old()

    def test_per_module_hash(self):
        self.lab.m['files']['gang_trader.py'] = '0' * 64
        self.lab.resign()
        with self.assertRaisesRegex(ValueError, 'SHA256'): self.lab.install()
        self.assert_old()

    def test_replay_and_downgrade(self):
        for v in ('1.3.2', '1.3.1', '1.3.0'):
            with self.subTest(version=v):
                self.lab.sign(version=v)
                with self.assertRaisesRegex(ValueError, 'replay'): self.lab.install()
                self.assert_old()

    def test_strict_versions(self):
        for v in ('1.4', '1.4.0.0', '01.4.0', '../1.4.0', '1.4.0rc1'):
            with self.subTest(version=v):
                self.lab.sign(version=v)
                with self.assertRaises(ValueError): self.lab.install()
                self.assert_old()

    def test_complete_package(self):
        self.lab.contents.pop('market_sources.py')
        self.lab.sign()
        with self.assertRaisesRegex(ValueError, 'complete'): self.lab.install()
        self.assert_old()

    def test_archive_name_attacks(self):
        for attack in ('../escape.py', './gang_trader.py', 'C:\\escape.py', '/escape.py', 'folder/', 'positions.mock.json'):
            with self.subTest(name=attack):
                entries = dict(self.lab.contents)
                entries.pop('market_sources.py')
                entries[attack] = b'pass\n'
                self.lab.sign(raw=make_zip(entries))
                with self.assertRaises(ValueError): self.lab.install()
                self.assert_old()

    def test_duplicate_archive_entries(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            for _ in range(4): z.writestr('gang_trader.py', b'pass\n')
        self.lab.sign(raw=b.getvalue())
        with self.assertRaises(ValueError): self.lab.install()
        self.assert_old()

    def test_zip_symlink(self):
        b = io.BytesIO()
        with zipfile.ZipFile(b, 'w') as z:
            for n in u.FILES:
                info = zipfile.ZipInfo(n)
                info.create_system = 3
                info.external_attr = (0o120777 << 16)
                z.writestr(info, b'pass\n')
        self.lab.sign(raw=b.getvalue())
        with self.assertRaises(ValueError): self.lab.install()
        self.assert_old()

    def test_uncompressed_size(self):
        self.lab.contents['gang_trader.py'] = b'#' + b'A' * u.MAX_FILE
        self.lab.sign()
        with self.assertRaisesRegex(ValueError, 'size'): self.lab.install()
        self.assert_old()

    def test_static_unsafe_candidates(self):
        for raw in (b'import socket\n', b'exec("pass")\n', b'x = object.__subclasses__()\n', b'open("positions.mock.json", "w")\n', b'def broken(\n'):
            with self.subTest(source=raw):
                self.lab.contents['gang_trader.py'] = raw
                self.lab.sign()
                with self.assertRaises((ValueError, SyntaxError)): self.lab.install()
                self.assert_old()

    def test_marker_config_scanner_guards(self):
        marker = self.lab.root / u.MARKER
        marker.write_bytes(b'WRONG')
        with self.assertRaises(ValueError): self.lab.install()
        marker.write_bytes(b'GANG_V14_DISPOSABLE_LAB\n')
        (self.lab.root / '.scanner_running').write_bytes(b'fixture')
        with self.assertRaises(RuntimeError): self.lab.install()
        with self.assertRaises(RuntimeError): u.recover(self.lab.root)
        self.assert_old()

    def test_hardlinked_target(self):
        target = self.lab.root / 'gang_trader.py'
        target.unlink()
        os.link(self.lab.outside, target)
        with self.assertRaises(ValueError): self.lab.install()

    def test_linked_target_and_backup_directory(self):
        if os.name == 'nt':
            self.skipTest('Windows symlink privilege dependent; use junction test separately')
        p = self.lab.root / 'gang_trader.py'
        p.unlink()
        p.symlink_to(self.lab.outside)
        with self.assertRaises(ValueError): self.lab.install()
        p.unlink()
        p.write_bytes(OLD)
        (self.lab.root / '.transactions').symlink_to(self.lab.base, target_is_directory=True)
        with self.assertRaises(ValueError): self.lab.install()
        self.assert_old()

    def test_linked_parent_root(self):
        if os.name == 'nt': self.skipTest('Windows junction case tested separately')
        alias = self.lab.base / 'alias'
        alias.symlink_to(self.lab.root, target_is_directory=True)
        with self.assertRaises(ValueError): u.recover(alias)

    def test_failure_rollback_at_every_mutation(self):
        points = ['prepared', 'applying', *['write:' + n for n in (*u.FILES, u.CONFIG)], 'before_commit']
        for point in points:
            with self.subTest(point=point):
                result = self.lab.child(GANG_LAB_FAIL_AT=point)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assert_old()
                self.assertEqual(u.recover(self.lab.root), 'ROLLED_BACK')

    def test_process_exit_at_every_checkpoint(self):
        points = ['backup_ready', 'prepared', 'applying', *['write:' + n for n in (*u.FILES, u.CONFIG)], 'before_commit', 'committed']
        for point in points:
            with self.subTest(point=point), tempfile.TemporaryDirectory(prefix='gang_v14_CRASH_') as td:
                lab = Lab(td)
                result = lab.child(GANG_LAB_CRASH_AT=point)
                self.assertEqual(result.returncode, 91, result.stderr)
                r = lab.child(recovery=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                if point == 'committed': self.assert_new(lab)
                else: self.assert_old(lab)
                self.assertEqual(lab.protected, lab.protected_snapshot())

    def wait_ready(self, lab, proc):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if (lab.root / '.fault-ready').exists(): return
            if proc.poll() is not None: self.fail('child exited before pause: ' + str(proc.returncode))
            time.sleep(.02)
        self.fail('timeout waiting for fault barrier')

    @contextmanager
    def paused(self, lab, point, recovery=False):
        proc = subprocess.Popen(lab.command(recovery), env=lab.env(GANG_LAB_PAUSE_AT=point), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.wait_ready(lab, proc)
            yield proc
        finally:
            if proc.poll() is None: proc.kill()
            proc.wait(timeout=10)
            ready = lab.root / '.fault-ready'
            if ready.exists(): ready.unlink()

    def test_real_force_kill_and_lock_release(self):
        for point in ('prepared', 'write:gang_trader.py', 'write:' + u.CONFIG, 'committed'):
            with self.subTest(point=point), tempfile.TemporaryDirectory(prefix='gang_v14_KILL_') as td:
                lab = Lab(td)
                with self.paused(lab, point) as proc:
                    proc.kill()  # SIGKILL on Linux, TerminateProcess on Windows.
                    proc.wait(timeout=10)
                result = lab.child(recovery=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if point == 'committed': self.assert_new(lab)
                else: self.assert_old(lab)
                self.assertEqual(lab.protected, lab.protected_snapshot())

    def test_concurrent_lock_contention(self):
        with self.paused(self.lab, 'prepared'):
            with self.assertRaises(TimeoutError):
                with u.locked(self.lab.root, timeout=.15): pass
        self.assertEqual(u.recover(self.lab.root), 'RECOVERED')
        self.assert_old()

    def test_two_installers_serialized(self):
        with self.paused(self.lab, 'prepared') as first:
            second = subprocess.Popen(self.lab.command(), env=self.lab.env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                time.sleep(.1)
                self.assertIsNone(second.poll())
                first.kill()
                first.wait(timeout=10)
                out, err = second.communicate(timeout=15)
                self.assertEqual(second.returncode, 0, out + err)
            finally:
                if second.poll() is None: second.kill(); second.wait(timeout=10)
        self.assert_new()

    def test_corrupt_backup_fails_before_any_restore(self):
        r = self.lab.child(GANG_LAB_CRASH_AT='write:gang_trader.py')
        self.assertEqual(r.returncode, 91)
        j = u.load_journal(self.lab.root)
        (self.lab.root / '.transactions' / j['id'] / 'market_sources.py').write_bytes(b'corrupt')
        mixed = self.lab.snapshot()
        with self.assertRaisesRegex(ValueError, 'SHA256'): u.recover(self.lab.root)
        self.assertEqual(mixed, self.lab.snapshot())
        self.assertEqual(u.load_journal(self.lab.root)['state'], 'APPLYING')

    def test_corrupt_journal_fails_closed(self):
        (self.lab.root / '.transaction.json').write_bytes(b'{broken')
        with self.assertRaises(ValueError): self.lab.install()
        self.assert_old()

    def test_journal_path_traversal(self):
        self.lab.child(GANG_LAB_CRASH_AT='prepared')
        j = u.load_journal(self.lab.root)
        j['id'] = '../../outside'
        (self.lab.root / '.transaction.json').write_bytes(u.canonical(j))
        with self.assertRaises(ValueError): u.recover(self.lab.root)
        self.assert_old()

    def test_committed_integrity_check(self):
        self.lab.install()
        (self.lab.root / 'market_sources.py').write_bytes(b'tampered')
        with self.assertRaisesRegex(ValueError, 'SHA256'): u.recover(self.lab.root)

    def test_interrupted_recovery_is_repeatable(self):
        self.lab.child(GANG_LAB_CRASH_AT='write:' + u.CONFIG)
        for name in (*u.FILES, u.CONFIG):
            with self.subTest(file=name):
                r = self.lab.child(recovery=True, GANG_LAB_CRASH_AT='restore:' + name)
                self.assertEqual(r.returncode, 91, r.stderr)
        self.assertEqual(u.recover(self.lab.root), 'RECOVERED')
        self.assert_old()

    def test_absent_originals_restored_as_absent(self):
        for n in u.FILES:
            (self.lab.root / n).unlink()
        self.lab.before = self.lab.snapshot()
        r = self.lab.child(GANG_LAB_FAIL_AT='write:' + u.CONFIG)
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assert_old()

    def test_backup_failure_leaves_originals(self):
        original = u.atomic_write
        def fail(path, data):
            if '.transactions' in Path(path).parts: raise OSError('simulated disk full')
            return original(path, data)
        with mock.patch.object(u, 'atomic_write', side_effect=fail):
            with self.assertRaises(OSError): self.lab.install()
        self.assert_old()
        self.assertFalse((self.lab.root / '.transaction.json').exists())

    def test_atomic_fsync_before_replace_crashes(self):
        for name in ('gang_trader.py', u.CONFIG, '.transaction.json'):
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix='gang_v14_FSYNC_') as td:
                lab = Lab(td)
                r = lab.child(GANG_LAB_CRASH_AT='atomic_fsync:' + name)
                self.assertEqual(r.returncode, 91, r.stderr)
                r = lab.child(recovery=True)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assert_old(lab)
                self.assertEqual(lab.protected, lab.protected_snapshot())

    def test_recovery_disk_failure_then_retry(self):
        self.lab.child(GANG_LAB_CRASH_AT='write:' + u.CONFIG)
        original = u.atomic_write
        counter = [0]
        def fail(path, data):
            if Path(path).name in u.FILES:
                counter[0] += 1
                if counter[0] == 2: raise PermissionError('simulated sharing violation / disk failure')
            return original(path, data)
        with mock.patch.object(u, 'atomic_write', side_effect=fail):
            with self.assertRaises(PermissionError): u.recover(self.lab.root)
        self.assertEqual(u.load_journal(self.lab.root)['state'], 'APPLYING')
        self.assertEqual(u.recover(self.lab.root), 'RECOVERED')
        self.assert_old()

    def test_duplicate_json_keys(self):
        self.lab.manifest.write_bytes(b'{"version":"1.4.0","version":"9.0.0"}')
        with self.assertRaisesRegex(ValueError, 'duplicate'): self.lab.install()
        self.assert_old()

    def test_total_uncompressed_limit(self):
        self.lab.contents = {n: b'#' + b'A' * 1_100_000 for n in u.FILES}
        self.lab.sign()
        with self.assertRaisesRegex(ValueError, 'size'): self.lab.install()
        self.assert_old()

    def test_manifest_schema_strictness(self):
        for extra in ({'schema': True}, {'schema': 2}, {'extra': 'unsigned-scope-attack'}):
            with self.subTest(fields=extra):
                self.lab.sign(**extra)
                with self.assertRaises(ValueError): self.lab.install()
                self.assert_old()

    def test_mock_business_and_state_compatibility(self):
        self.lab.install()
        # Execute ONLY the exact trusted fixture generated above, never a fetched candidate.
        self.assertEqual((self.lab.root / 'gang_trader.py').read_bytes(), BUSINESS)
        scope = {}
        exec(compile(BUSINESS, '<generated-mock-business>', 'exec'), scope)
        state = json.loads((self.lab.root / 'positions.mock.json').read_bytes())
        before = json.loads(json.dumps(state))
        bought = scope['trade'](state, 'buy', '2', '100.00')
        sold = scope['trade'](bought, 'sell', '1', '120.00')
        self.assertEqual(sold['cash'], '9920.00')
        self.assertEqual(sold['position'], '4')
        self.assertEqual(len(sold['records']), 3)
        self.assertEqual(state, before)
        for side, qty, price in [('buy', '999999', '100'), ('sell', '999', '100'), ('buy', '-1', '100'), ('invalid', '1', '100')]:
            with self.assertRaises(ValueError): scope['trade'](state, side, qty, price)
        self.assertEqual(state, before)

    def test_commit_marker_write_failure_rolls_back(self):
        original = u.save_journal
        def fail(root, journal):
            if journal['state'] == 'COMMITTED': raise OSError('commit write failed')
            return original(root, journal)
        with mock.patch.object(u, 'save_journal', side_effect=fail):
            with self.assertRaises(OSError): self.lab.install()
        self.assert_old()
        self.assertEqual(u.recover(self.lab.root), 'ROLLED_BACK')

    def test_atomic_replace_failure_leaves_recoverable_journal(self):
        original = u.os.replace
        def fail(source, target):
            if Path(target).name == 'market_sources.py' and Path(target).parent == self.lab.root:
                raise PermissionError('injected replacement failure')
            return original(source, target)
        with mock.patch.object(u.os, 'replace', side_effect=fail):
            with self.assertRaises(PermissionError): self.lab.install()
        self.assertEqual(u.load_journal(self.lab.root)['state'], 'APPLYING')
        self.assertEqual(u.recover(self.lab.root), 'RECOVERED')
        self.assert_old()

    def test_null_required_journal_hash_rejected(self):
        self.lab.child(GANG_LAB_CRASH_AT='prepared')
        j = u.load_journal(self.lab.root)
        j['target']['gang_trader.py'] = None
        (self.lab.root / '.transaction.json').write_bytes(u.canonical(j))
        with self.assertRaises(ValueError): u.recover(self.lab.root)
        self.assert_old()

    @unittest.skipUnless(os.name == 'nt', 'requires actual Windows file sharing semantics')
    def test_windows_open_file_sharing_violation_recovery(self):
        with open(self.lab.root / 'gang_trader.py', 'rb'):
            with self.assertRaises(PermissionError): self.lab.install()
        self.assertEqual(u.recover(self.lab.root), 'RECOVERED')
        self.assert_old()

    @unittest.skipUnless(os.name == 'nt', 'requires actual Windows NTFS junction support')
    def test_windows_junction_guard(self):
        alias = self.lab.base / 'junction'
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', str(alias), str(self.lab.root)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        try:
            with self.assertRaises(ValueError): u.recover(alias)
        finally:
            os.rmdir(alias)


class ReportResult(unittest.TextTestResult):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.events = []
    def addSuccess(self, test):
        super().addSuccess(test); self.events.append({'test': str(test), 'status': 'PASS'})
    def addSkip(self, test, reason):
        super().addSkip(test, reason); self.events.append({'test': str(test), 'status': 'SKIP', 'reason': reason})
    def addFailure(self, test, err):
        super().addFailure(test, err); self.events.append({'test': str(test), 'status': 'FAIL', 'detail': self._exc_info_to_string(err, test)})
    def addError(self, test, err):
        super().addError(test, err); self.events.append({'test': str(test), 'status': 'ERROR', 'detail': self._exc_info_to_string(err, test)})
    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.events.append({'test': str(subtest), 'status': 'PASS' if err is None else 'FAIL',
                            **({'detail': self._exc_info_to_string(err, test)} if err else {})})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', required=True)
    args = ap.parse_args()
    start = time.time()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Acceptance)
    result = unittest.TextTestRunner(verbosity=2, resultclass=ReportResult).run(suite)
    report = {'platform': platform.platform(), 'os_name': os.name, 'python': sys.version,
              'windows_machine_acceptance': os.name == 'nt', 'physical_power_loss_tested': False, 'cryptography': __import__('cryptography').__version__,
              'source_sha256': u.digest(SCRIPT.read_bytes()), 'test_sha256': u.digest(Path(__file__).read_bytes()),
              'tests_run': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': len(result.skipped), 'elapsed_seconds': time.time() - start,
              'events': result.events, 'scope': 'synthetic fixtures only; no real scanner/business/account validation'}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
