"""Two-stage persistent fixture for an EXTERNAL controlled power-cycle.
Never shuts down, reboots or kills the host. Preparation requires actual Windows 11.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import uuid
import gang_updater_v14_reviewed as u
from test_release_acceptance import Lab


def require_windows11():
    if os.name != 'nt' or sys.getwindowsversion().build < 22000:
        raise RuntimeError('Actual dedicated Windows 11 machine required')


def prepare(point):
    require_windows11()
    base = Path(__file__).resolve().parent / 'acceptance-results' / ('powerloss-' + uuid.uuid4().hex)
    base.mkdir(parents=True, exist_ok=False)
    lab = Lab(base)
    expected = {
        'schema': 1, 'point': point, 'platform': platform.platform(),
        'source_sha256': u.digest(Path(u.__file__).read_bytes()),
        'before': {n: base64.b64encode(d).decode() if d is not None else None for n, d in lab.before.items()},
        'target': {n: u.digest(d) for n, d in lab.contents.items()},
        'protected': {Path(n).name: h for n, h in lab.protected.items()}}
    u.atomic_write(base / 'powerloss-evidence.json', u.canonical(expected))
    log = open(base / 'child.log', 'wb')
    try:
        child = subprocess.Popen(lab.command(), env=lab.env(GANG_LAB_PAUSE_AT=point),
                                 stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    finally:
        log.close()
    deadline = time.monotonic() + 15
    while not (lab.root / '.fault-ready').exists():
        if child.poll() is not None: raise RuntimeError('child exited; inspect child.log')
        if time.monotonic() > deadline:
            child.kill(); child.wait(timeout=10)
            raise TimeoutError('fault barrier timeout')
        time.sleep(.05)
    print('PREPARED; child paused at ' + point + '. This is NOT a power-loss PASS.')
    print('Only on your dedicated disposable test machine, perform an externally controlled hard power cycle.')
    print('After restart run:')
    print('"' + sys.executable + '" "' + str(Path(__file__).resolve()) + '" verify --case "' + str(base) + '"')
    return 0


def verify(case, record_external_power_cycle=False):
    require_windows11()
    base = Path(case).absolute()
    # Only consume our generated fixture location, never an arbitrary scanner root.
    allowed = Path(__file__).resolve().parent / 'acceptance-results'
    if base.parent != allowed or not base.name.startswith('powerloss-'):
        raise ValueError('case must be generated in this bundle acceptance-results directory')
    for p in (allowed, base): u.plain(p, directory=True)
    u.plain(base / 'powerloss-evidence.json')
    e = u.read_json(base / 'powerloss-evidence.json')
    if e['source_sha256'] != u.digest(Path(u.__file__).read_bytes()):
        raise ValueError('updater source changed since preparation')
    root = base / 'disposable-lab'
    result = u.recover(root)
    if e['point'] == 'committed':
        u.verify_targets(root, e['target'])
        if u.read_json(root / u.CONFIG)['version'] != '1.4.0': raise ValueError('version mismatch')
    else:
        for n, enc in e['before'].items():
            if n not in (*u.FILES, u.CONFIG): raise ValueError('invalid expected filename')
            if (root / n).read_bytes() != base64.b64decode(enc, validate=True):
                raise ValueError('rollback mismatch: ' + n)
    for name, h in e['protected'].items():
        if name not in ('outside-sentinel.bin', 'positions.mock.json', 'trades.mock.json', 'account.mock.json'):
            raise ValueError('invalid protected filename')
        p = base / name if name == 'outside-sentinel.bin' else root / name
        if u.digest(p.read_bytes()) != h: raise ValueError('protected data changed')
    report = {'fixture_integrity': 'PASS', 'recovery': result, 'platform': platform.platform(),
              'source_sha256': e['source_sha256'], 'checkpoint': e['point'],
              'external_power_cycle_operator_attested': record_external_power_cycle,
              'physical_power_loss_automatically_verified': False,
              'note': 'Operator attestation is not independent evidence of power removal or hardware durability.'}
    u.atomic_write(base / 'powerloss-result.json', u.canonical(report))
    print(json.dumps(report, indent=2))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='action', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--checkpoint', choices=['prepared', 'write:market_sources.py', 'write:update_config_v14.json', 'committed'], default='write:market_sources.py')
    p = sub.add_parser('verify')
    p.add_argument('--case', required=True)
    p.add_argument('--attest-external-power-cycle', action='store_true')
    a = ap.parse_args()
    try:
        return prepare(a.checkpoint) if a.action == 'prepare' else verify(a.case, a.attest_external_power_cycle)
    except Exception as e:
        print('FAIL/BLOCKED: ' + str(e), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
