"""Build credential-free offline Windows x64 test upgrade from verified inputs."""
from pathlib import Path
import json, zipfile, shutil, hashlib, urllib.request

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dist/labsch-pc-tes-0.4.0-test1'
OUT.mkdir(parents=True,exist_ok=True)
runtime=OUT/'runtime'; runtime.mkdir(exist_ok=True)
embed=Path('/root/labsch-python-embed.zip')
with zipfile.ZipFile(embed) as z: z.extractall(runtime)
packages=runtime/'Lib/site-packages'; packages.mkdir(parents=True,exist_ok=True)
inputs=[]
for wheel in sorted(Path('/root/labsch-win-wheels').glob('*.whl')):
    with urllib.request.urlopen('https://pypi.org/pypi/'+wheel.name.split('-')[0]+'/'+wheel.name.split('-')[1]+'/json',timeout=30) as r:
        metadata=json.load(r)
    digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
    assert any(x['filename']==wheel.name and x['digests']['sha256']==digest for x in metadata['urls'])
    inputs.append(dict(file=wheel.name,sha256=digest,verified_against='PyPI release JSON'))
    with zipfile.ZipFile(wheel) as z:z.extractall(packages)
# Explicit embedded Python paths (no pip, PATH, user site, registry dependency).
(runtime/'python312._pth').write_text('python312.zip\n.\n..\nLib/site-packages\nLib/site-packages/win32\nLib/site-packages/win32/lib\nLib/site-packages/Pythonwin\nimport site\n',encoding='ascii')
for dll in (packages/'pywin32_system32').glob('*.dll'): shutil.copy2(dll,runtime/dll.name)
import sys
sys.path.insert(0,str(ROOT/'agent'))
from upgrade import MODULES
for name in MODULES+['upgrade.py','upgrade.bat']:shutil.copy2(ROOT/'agent'/name,OUT/name)
shutil.copy2(ROOT/'docs/DOWNLOAD_TEST_RELEASE.md',OUT/'README.txt')
inputs.append(dict(file=embed.name,sha256=hashlib.sha256(embed.read_bytes()).hexdigest(),source='https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip'))
(OUT/'DEPENDENCIES.json').write_text(json.dumps(inputs,indent=2))
manifest={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(OUT.rglob('*')) if p.is_file() and p.name!='MANIFEST.json'}
(OUT/'MANIFEST.json').write_text(json.dumps(manifest,indent=2))
# Compare actual configured token without printing it or embedding it.
env=Path('/root/.hermes/.env').read_text()
secrets=[line.split('=',1)[1].strip().strip('\"\'') for line in env.splitlines() if line.startswith('SCHOOL_API_TOKEN=')]
assert secrets and all(secrets)
for p in OUT.rglob('*'):
    if p.is_file():
        data=p.read_bytes()
        assert not any(s.encode() in data for s in secrets), 'credential leak: '+str(p)
        assert p.name not in ('config.ini','.env')
archive=OUT.parent/(OUT.name+'.zip')
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.rglob('*')):
        if p.is_file():z.write(p,str(p.relative_to(OUT)))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for name,sha in manifest.items():assert hashlib.sha256(z.read(name)).hexdigest()==sha
print(json.dumps(dict(artifact=str(archive),sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),bytes=archive.stat().st_size,files=len(manifest)+1,credential_scan='passed'),indent=2))
