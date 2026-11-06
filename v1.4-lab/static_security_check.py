"""Reproducible structural checks; not a proof that arbitrary Python is safe."""
import ast
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent

def main():
    errors = []
    hashes = {}
    for p in sorted(ROOT.glob('*.py')):
        data = p.read_bytes()
        hashes[p.name] = hashlib.sha256(data).hexdigest()
        try:
            compile(ast.parse(data, filename=p.name), p.name, 'exec')
        except SyntaxError as e:
            errors.append(f'{p.name}:{e.lineno}: {e.msg}')
    p = ROOT / 'gang_updater_v14_reviewed.py'
    tree = ast.parse(p.read_bytes())
    imports = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import): imports.update(a.name.split('.')[0] for a in n.names)
        if isinstance(n, ast.ImportFrom): imports.add((n.module or '').split('.')[0])
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in {'exec', 'eval', '__import__'}:
            errors.append('dynamic code execution in updater')
    for name in imports & {'subprocess', 'socket', 'urllib', 'requests', 'http', 'ctypes'}:
        errors.append('updater network/process/native import: ' + name)
    # These are concrete source invariants, supplemented by behavioral tests.
    for required in ('verify_package', 'restore', 'recover_locked', 'locked', 'static_check', 'sync_dir'):
        if required not in {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}:
            errors.append('missing security function: ' + required)
    report = {'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'source_hashes': hashes,
              'limitations': 'AST policy does not sandbox Python or validate real business compatibility.'}
    print(json.dumps(report, indent=2))
    return bool(errors)

if __name__ == '__main__':
    sys.exit(main())
