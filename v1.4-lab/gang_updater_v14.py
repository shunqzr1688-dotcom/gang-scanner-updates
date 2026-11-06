"""GANG V1.4 standalone signed updater. Never touches folders outside configured root.
Requires: pip install cryptography. Python >=3.10.
"""
import argparse, base64, hashlib, io, json, os, pathlib, re, shutil, ssl, subprocess, sys, tempfile, time, urllib.request, zipfile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

FILES = {'gang_trader.py', 'market_sources.py', 'test_official_api.py', 'test_sources_fix.py'}
REQUIRED = {'gang_trader.py', 'market_sources.py'}
MAX_ZIP = 4_000_000

def atomic_write(path, data):
    temp = path.with_name(path.name + '.tmp')
    with open(temp, 'wb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(temp, path)

def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def download(url, ca_cert=None):
    if not url.startswith('https://'):
        raise ValueError('Only HTTPS URLs allowed')
    ctx = ssl.create_default_context(cafile=ca_cert) if ca_cert else ssl.create_default_context()
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent':'GANG-Updater/1.4'}), timeout=15, context=ctx) as resp:
        payload = resp.read(MAX_ZIP + 1)
    if len(payload) > MAX_ZIP: raise ValueError('download too large')
    return payload

def verify_manifest(manifest, key_b64):
    signature = base64.b64decode(manifest['signature'], validate=True)
    pub = base64.b64decode(key_b64, validate=True)
    unsigned = {k:v for k,v in manifest.items() if k != 'signature'}
    Ed25519PublicKey.from_public_bytes(pub).verify(signature, canonical(unsigned))
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,48}', str(manifest['version'])):
        raise ValueError('unsafe version')
    if not re.fullmatch(r'[a-fA-F0-9]{64}', str(manifest['sha256'])):
        raise ValueError('bad sha256')
    return unsigned

def safe_stage(raw, stage):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        names=set()
        for info in z.infolist():
            if info.is_dir(): continue
            name = pathlib.PurePosixPath(info.filename)
            if len(name.parts)!=1 or name.name not in FILES or name.name in names:
                raise ValueError('unexpected or duplicate zip entry: '+info.filename)
            if info.file_size>2_000_000 or info.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError('oversize or symlink entry')
            names.add(name.name)
            (stage/name.name).write_bytes(z.read(info))
    if not REQUIRED.issubset(names): raise ValueError('required modules missing')

def health(root):
    for name in REQUIRED:
        result = subprocess.run([sys.executable, '-m', 'py_compile', str(root/name)], cwd=root, capture_output=True, text=True, timeout=15)
        if result.returncode: raise RuntimeError('compile failed: '+name+' '+result.stderr[-500:])
    result = subprocess.run([sys.executable, str(root/'gang_trader.py'), '--test'], cwd=root, capture_output=True, text=True, timeout=30)
    if result.returncode: raise RuntimeError('health check failed: '+(result.stdout+result.stderr)[-500:])
    return result.stdout.strip()[-300:]

def check(root, config, dry_run=False):
    root=root.resolve(strict=True)
    cfg_path = root/'update_config_v14.json'
    cfg = read_json(cfg_path)
    if not cfg.get('enabled',False): return 'DISABLED'
    if cfg.get('install_root_id') != 'GANG_V14_ISOLATED':
        raise ValueError('isolated root guard missing')
    if not (root/'.gang_v14_isolated').is_file():
        raise ValueError('isolated directory marker missing')
    if not cfg.get('public_key_ed25519') or not cfg.get('manifest_url'):
        raise ValueError('manifest URL or pinned public key missing')
    # A custom CA is only permitted for explicit localhost integration tests.
    ca=cfg.get('test_ca_cert')
    if ca and (not cfg.get('test_mode') or not cfg['manifest_url'].startswith('https://localhost:')):
        raise ValueError('custom CA restricted to localhost test mode')
    manifest=json.loads(download(cfg['manifest_url'], ca))
    verify_manifest(manifest, cfg['public_key_ed25519'])
    old=str(cfg['version']); new=str(manifest['version'])
    if new==old: return 'UP_TO_DATE '+old
    if not manifest['zip_url'].startswith('https://'): raise ValueError('ZIP URL must be HTTPS')
    if ca and not manifest['zip_url'].startswith('https://localhost:'): raise ValueError('test zip must be localhost')
    raw=download(manifest['zip_url'], ca)
    if hashlib.sha256(raw).hexdigest().lower()!=manifest['sha256'].lower():
        raise ValueError('SHA256 mismatch')
    with tempfile.TemporaryDirectory(prefix='gang_v14_stage_') as temp:
        stage=pathlib.Path(temp)
        safe_stage(raw,stage)
        health(stage)
        if dry_run: return 'DRY_RUN_VALID '+new
        # Never replace modules while running a scanner: the caller must confirm scanner stopped.
        if not cfg.get('allow_install_while_scanner_running',False):
            # The isolated lab has no scanner running, but production updates require a supervisor.
            if not cfg.get('test_mode',False): return 'VERIFIED_PENDING_MAINTENANCE '+new
        backup=root/'backups'/('before_'+new+'_'+str(int(time.time()*1000)))
        backup.mkdir(parents=True,exist_ok=False)
        originals={name:(root/name).exists() for name in FILES}
        for name,exists in originals.items():
            if exists: shutil.copy2(root/name,backup/name)
        shutil.copy2(cfg_path, backup/'update_config_v14.json')
        try:
            for name in FILES:
                if (stage/name).exists(): atomic_write(root/name,(stage/name).read_bytes())
            health(root)  # mandatory post-install test
            cfg['version']=new
            atomic_write(cfg_path,(json.dumps(cfg,ensure_ascii=False,indent=2)+'\n').encode())
            return 'UPDATED '+old+' -> '+new+' backup='+str(backup)
        except BaseException:
            for name,exists in originals.items():
                if exists: atomic_write(root/name,(backup/name).read_bytes())
                elif (root/name).exists(): (root/name).unlink()
            atomic_write(cfg_path,(backup/'update_config_v14.json').read_bytes())
            health(root)  # verify restoration; error propagates if broken
            raise

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--interval-seconds',type=float,default=0)
    parser.add_argument('--cycles',type=int,default=1)
    args=parser.parse_args()
    root=pathlib.Path(args.root)
    if args.cycles<1 or args.interval_seconds<0: parser.error('invalid schedule')
    for i in range(args.cycles):
   try:
            print(check(root,None,args.dry_run),flush=True)
        except Exception as e:
            print('UPDATE_REJECTED '+type(e).__name__+': '+str(e),flush=True)
            if args.cycles==1: return 1
        if i+1<args.cycles: time.sleep(args.interval_seconds)
    return 0
if __name__=='__main__': sys.exit(main())
