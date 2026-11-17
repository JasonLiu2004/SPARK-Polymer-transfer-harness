"""Install independent official Python and pinned MD packages, Windows x64."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
URL = 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip'
SHA256 = '009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b'

if __name__ == '__main__':
    if sys.platform != 'win32':
        raise SystemExit('This installer targets Windows x64')
    runtime = ROOT/'.runtime'
    runtime.mkdir(exist_ok=True)
    archive = runtime/'python311.zip'
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('Python archive checksum mismatch')
    python_dir = runtime/'python311'
    with zipfile.ZipFile(archive) as package:
        for name in package.namelist():
            if not (python_dir/name).resolve().is_relative_to(python_dir.resolve()):
                raise ValueError('Unsafe archive path')
        package.extractall(python_dir)
    (python_dir/'python311._pth').write_text(
        'python311.zip\n.\n../md_env/Lib/site-packages\nimport site\n', encoding='utf-8')
    packages = runtime/'md_env'/'Lib'/'site-packages'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', '--target', str(packages),
                    'openmm==8.6.1', 'numpy==1.26.4'], check=True)
    with tempfile.TemporaryDirectory(prefix='spe_openmm_') as mirror:
        subprocess.run([str(python_dir/'python.exe'), str(ROOT/'openmm_worker.py'), '--probe'],
                       check=True, timeout=30, env=dict(os.environ, SPE_OPENMM_MIRROR=mirror))
    (runtime/'md_installation.json').write_text(json.dumps(
        {'python_url': URL, 'python_archive_sha256': SHA256,
         'python_version': '3.11.9', 'openmm_version': '8.6.1', 'numpy_version': '1.26.4'}, indent=2))
