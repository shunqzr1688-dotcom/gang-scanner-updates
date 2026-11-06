# GANG V1.4 release preparation — disposable labs only

This branch is NOT a production release. Never run against GANG V1.3.2 or real account/state directories. Root `manifest.json` remains unchanged (`1.3.2`, `no_update`).

## Files and scope

- `gang_updater_v14_reviewed.py`: offline signed-package installation, strict four-module manifest, Ed25519 pinned public key, ZIP and per-file SHA256, conservative Python AST policy, independent lab guards, OS advisory locking, durable backup hashes, journal and repeatable startup rollback.
- `gang_updater_v14.py`: compatibility CLI entry, delegates to the reviewed implementation. Old online `check()` API/manifest format is intentionally not retained.
- `test_release_acceptance.py`: generates its own mock modules, ephemeral signing key, synthetic positions/ledger/cash, and outside-root integrity sentinel. Exercises the real updater in temporary roots and child processes. No real production module is needed or accessed.
- `static_security_check.py`: syntax and structural updater checks; no network or downloaded-candidate execution.
- `Run-Windows11-Acceptance.cmd` / `windows_acceptance.ps1`: local NTFS Windows 11 acceptance runner.
- `powerloss_lab.py`: persistent disposable power-cycle case preparation and post-reboot verification. Never powers off or reboots the host.
- `test_gang_v14_independent.py`: preserved older static/standalone fixture checker. Its results do not replace the new actual updater tests.

## Linux/cloud reproduction

Python >=3.10. Install dependencies only into a new disposable venv:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-lab.txt
.venv/bin/python static_security_check.py
.venv/bin/python test_release_acceptance.py --report linux-acceptance.json
```

The acceptance script removes its own temporary fixtures on completion. Fault variables `GANG_LAB_FAIL_AT`, `GANG_LAB_CRASH_AT`, `GANG_LAB_PAUSE_AT` are laboratory-only injection hooks; child environment strips inherited account/cloud variables. Generated private test keys exist only in memory. No production signing credentials are used.

## Transaction/recovery protocol

1. Validate nonlinked lab root/ancestors, marker contents, `test_mode=true`, root identity, managed paths, and scanner stop marker.
2. Acquire persistent `.update.lock` (`flock` Linux, byte-range `msvcrt.locking` Windows), revalidate root, recover any incomplete transaction.
3. Verify strict manifest schema and pinned Ed25519 signature, increasing three-part version, bounded archive, exact names of all four modules, no duplicates/links/traversal, uncompressed limits, module hashes and AST checks.
4. Save originals including config to unique `.transactions/<id>`, flush files, verify all backup SHA256 values, and persist PREPARED journal before installation writes.
5. Persist APPLYING, atomically replace each managed file and configuration, verify the installed set, then persist COMMITTED. Unmanaged files are never selected for writes.
6. On an exception or next `--recover`, validate ALL backup hashes before restoration, restore the old complete set, verify, persist ROLLED_BACK. Interrupted restoration can be retried. COMMITTED records verify the new set; corruption fails closed without silently reporting success.

Backups and completed journals remain for audit; no automatic deletion. An incomplete backup made before PREPARED is orphaned and never used for recovery. Fault crashes can leave uniquely named temporary files; they are never imported or treated as modules. Do not delete journals/backups to bypass a failure.

## Offline manifest contract

Signed JSON has exactly `schema` (integer 1), `version` (strict x.y.z), `sha256` (ZIP hash), `files` (map of every managed filename to hash), and `signature` (base64 Ed25519 signature over sorted compact UTF-8 JSON excluding signature). Complete package contains exactly `gang_trader.py`, `market_sources.py`, `test_official_api.py`, `test_sources_fix.py`. The root config contains pinned `public_key_ed25519`, `version`, `enabled=true`, `install_root_id="GANG_V14_ISOLATED"`, `test_mode=true`; marker bytes are exactly `GANG_V14_DISPOSABLE_LAB\n`.

Use fixture generation from the test suite instead of pointing the CLI at an existing installation. This branch deliberately does not publish a manifest, download packages, supervise real scanner processes, or execute supplied business code. `--dry-run` validates the package but may recover an already interrupted transaction; it is not a no-write inspection command. Use it only in disposable roots.

## Windows 11 one-click isolation acceptance

1. Copy the complete bundle to a **dedicated disposable Windows 11 machine** on local NTFS; Python >=3.10 and PowerShell are required. No administrator permission is needed. Do not place the bundle in a live scanner directory.
2. Double-click `Run-Windows11-Acceptance.cmd`. It creates a unique venv, installs the pinned crypto dependency using pip/TLS, and runs structural checks and the full suite. If local PowerShell execution policy blocks the script, the runner reports the restriction; it does not change system execution policy. Follow your managed device policy before retrying.
3. Offline alternative: `Run-Windows11-Acceptance.cmd -Offline -PythonExe "C:\path\python.exe"` requires cryptography already installed in that interpreter; the report records the actual version.
4. Preserve `acceptance-results/windows11-<id>/`: host OS metadata, full transcript, `static-security.json`, and `acceptance.json`. Check zero failures/errors. Windows sharing violation, native lock, TerminateProcess and junction cases must execute. Linux symlink-specific cases are skipped on Windows and replaced by a native junction case.

The script neither enumerates nor terminates GANG processes; it kills only test child handles it created. This suite's PASS establishes synthetic updater behavior on the recorded machine, not real scanner business compatibility or physical power-loss acceptance.

## Real power-loss acceptance — explicit external operation required

Only use a dedicated disposable Windows 11 machine where external hard power removal is safe. The scripts never power off the machine. After one-click acceptance, use its venv Python:

```text
<venv>\Scripts\python.exe powerloss_lab.py prepare --checkpoint write:market_sources.py
```

It creates a persistent fixture and pauses its own updater child after a synced partial installation. Record the printed case path and checkpoint, OS build, filesystem, disk/VM/cache configuration and external power-control evidence. Perform a **real externally controlled power loss** on the dedicated test machine, then reboot and run the printed verify command. Add `--attest-external-power-cycle` only if the operation actually occurred; this is an operator attestation, never automatic hardware proof.

Repeat with separate fresh cases at `prepared`, `write:market_sources.py`, `write:update_config_v14.json`, and `committed`. All precommit cases must restore old files+version; committed must preserve the complete new set. Every case must preserve synthetic positions/trades/cash and the outside sentinel. Preserve `powerloss-evidence.json`, `powerloss-result.json`, `child.log` and external event evidence for review.

A verify call before the child has exited will fail due to lock contention. Python `os._exit`, SIGKILL, TerminateProcess, VM process termination and a normal reboot are **not** automatically equivalent to physical power removal. VM tests only qualify the tested VM/storage behavior.

## Known limits / release gates

- No Windows execution or physical power loss was performed in the Linux cloud environment. Windows code is supplied for actual execution and review, not certified.
- POSIX directory metadata is fsynced. Portable Python provides no Windows directory fsync here; NTFS/storage-cache/hardware persistence is unproven. No power-loss guarantee is made.
- Static AST allowlist is conservative and can reject genuine business imports. It is not a sandbox, and signatures do not make code safe. No downloaded candidate is executed by the updater.
- No production scanner supervisor/handshake exists; `.scanner_running` is a lab marker. All scanner readers would need the same exclusion protocol before any future production integration.
- Locks are local advisory locks, not distributed locks. Network filesystems are unsupported. Same-user adversarial path races and journal/backup rewriting are outside the current trust model; lab directories must be private.
- Journal/backup hashes detect accidental corruption, not a local attacker able to rewrite both. Corruption or storage failure blocks recovery rather than guessing; retain evidence.
- Real `gang_trader.py`/`market_sources.py`, real schema migration and paper-trading integration are absent. Synthetic compatibility PASS does not validate the real business modules.
- No production key/rotation management, release distribution, GUI, scheduled service, automatic backup retention or production deployment is included. Those need design and acceptance before promotion.
- Production deployment and real funds require separate explicit user approval after Windows and business gates pass.
