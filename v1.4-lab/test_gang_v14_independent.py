
#!/usr/bin/env python3
"""GANG V1.4 independent, read-only offline security tests.

Usage:
 python test_gang_v14_independent.py --updater "path/to/gang_updater_v14_reviewed.py"

Does not import or execute updater, access network, or write to updater directory.
Only creates temporary files in an OS-managed temporary directory.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def result(name, status, detail):
    print(f'[{status}] {name}: {detail}', flush=True)
    return {'test': name, 'status': status, 'detail': detail}


def main():
    ap = argparse.ArgumentParser(description='Offline non-invasive GANG V1.4 test')
    ap.add_argument('--updater', required=True, help='Path to updater Python source')
    ap.add_argument('--json-report', help='Optional report output path (not in production scanner)')
    args = ap.parse_args()
    source = Path(args.updater).expanduser().absolute()
    reports = []

    def add(n, s, d):
        reports.append(result(n, s, d))

    if not source.is_file():
        add('Source file', 'FAIL', 'File not found: ' + str(source))
        return 2
    if source.is_symlink():
        add('Source file', 'FAIL', 'Symlink source is not accepted')
        return 2

    try:
        raw = source.read_bytes()
        text = raw.decode('utf-8-sig')
        tree = ast.parse(text, filename=source.name)
        compile(tree, str(source), 'exec')
        add('Python syntax', 'PASS', 'AST parse and compile succeeded; source not executed')
    except Exception as e:
        add('Python syntax', 'FAIL', f'{type(e).__name__}: {e}')
        return 1

    print('SOURCE_SHA256', hashlib.sha256(raw).hexdigest())
    nodes = list(ast.walk(tree))
    calls = set()
    for n in nodes:
        if isinstance(n, ast.Call):
            try:
                calls.add(ast.unparse(n.func))
            except Exception:
                pass

    for label, tokens in [
        ('Ed25519 verification code', ['Ed25519PublicKey', '.verify(']),
        ('SHA256 check code', ['sha256', 'hexdigest']),
        ('Backup code', ['backup']),
        ('Rollback code', ['except', 'backup']),
        ('Path validation code', ['resolve', 'symlink']),
        ('Isolated marker/config code', ['test_mode', 'isolated']),
    ]:
        missing = [t for t in tokens if t.lower() not in text.lower()]
        add(
            label,
            'REVIEW' if not missing else 'WARN',
            'Indicators present; NOT proof of correct behavior'
            if not missing else 'Missing textual indicators: ' + ', '.join(missing)
        )

    dangerous = [
        c for c in sorted(calls)
        if any(x in c for x in ('subprocess.', 'os.system', 'eval', 'exec', 'Popen'))
    ]
    add(
        'Executable update risk', 'REVIEW',
        'Execution-related calls: ' +
        (', '.join(dangerous) if dangerous else 'none detected via call names') +
        '; signed code still requires trusted keys and controlled execution'
    )

    with tempfile.TemporaryDirectory(prefix='gang_v14_independent_') as td:
        t = Path(td)
        data = b'GANG_V14_OFFLINE_TEST_PAYLOAD'
        expected = '9' * 64
        actual = hashlib.sha256(data).hexdigest()

        add(
            'SHA256 positive/negative fixture',
            'PASS' if actual == hashlib.sha256(data).hexdigest()
            and actual != expected else 'FAIL',
            'Python hashlib fixture only; does not execute updater hash verification'
        )

        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
            from cryptography.exceptions import InvalidSignature

            private = Ed25519PrivateKey.generate()
            public = private.public_key()
            signature = private.sign(data)
            public.verify(signature, data)
            rejected = False
            try:
                public.verify(signature, data + b'changed')
            except InvalidSignature:
                rejected = True

            add(
                'Ed25519 positive/negative fixture',
                'PASS' if rejected else 'FAIL',
                'cryptography fixture only; updater key/verification path not exercised'
            )
        except ImportError:
            add(
                'Ed25519 positive/negative fixture', 'SKIP',
                'Install cryptography to run independent crypto fixture'
            )
        except Exception as e:
            add('Ed25519 positive/negative fixture', 'FAIL', repr(e))

        zip_path = t / 'malicious.zip'
        with zipfile.ZipFile(zip_path, 'w') as z:
            z.writestr('../escape.txt', b'evil')
            z.writestr('safe.txt', b'ok')

        with zipfile.ZipFile(zip_path) as z:
            entries = z.namelist()
            unsafe = [
                n for n in entries
                if '..' in Path(n.replace('\\', '/')).parts or n.startswith('/')
            ]

        add(
            'ZIP traversal fixture',
            'PASS' if unsafe == ['../escape.txt'] else 'FAIL',
            'Malicious ZIP generated/detected locally; updater ZIP handling NOT executed'
        )

        original = t / 'original.txt'
        backup = t / 'backup.txt'
        original.write_bytes(b'old')
        backup.write_bytes(original.read_bytes())
        original.write_bytes(b'new')
        original.write_bytes(backup.read_bytes())

        add(
            'Backup/rollback fixture',
            'PASS' if original.read_bytes() == b'old' else 'FAIL',
            'Standalone temporary-file rollback only; updater rollback NOT executed'
        )

        cli = all(tk in text for tk in ('--root', '--dry-run'))
        add(
            'CLI isolation switches',
            'REVIEW' if cli else 'WARN',
            'Switches present; actual fail-closed behavior NOT exercised'
            if cli else 'Expected switches not found'
        )

    add(
        'Windows ACL/interrupted update', 'SKIP',
        'Requires dedicated controlled Windows fault-injection test'
    )
    add(
        'Real updater signed package/rollback', 'SKIP',
        'Requires audited isolated fixture and trusted test signing key; intentionally not run'
    )
    add(
        'Production scanner/records', 'PASS',
        'No updater import/execution; script never opens production scanner paths'
    )

    counts = {
        s: sum(r['status'] == s for r in reports)
        for s in ('PASS', 'FAIL', 'WARN', 'REVIEW', 'SKIP')
    }
    print('SUMMARY', json.dumps(counts, ensure_ascii=False))

    if args.json_report:
        out = Path(args.json_report).expanduser().absolute()
        if out == source or out.is_symlink():
            print('Refusing unsafe report destination', file=sys.stderr)
            return 2
        out.write_text(
            json.dumps({
                'source': str(source),
                'source_sha256': hashlib.sha256(raw).hexdigest(),
                'results': reports,
                'counts': counts
            }, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )

    return 1 if counts['FAIL'] else 0


if __name__ == '__main__':
    sys.exit(main())
