"""Restore the pinned official portable Windows xTB runtime into this project."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

URL = 'https://github.com/grimme-lab/xtb/releases/download/v6.7.1/xtb-6.7.1pre-windows-x86_64.zip'
SHA256 = '043e578da4a7e114a4d584972959a875e3ffb9f2767a86723b95aa6719d28d9c'


def main():
    root = Path(__file__).resolve().parent / '.runtime' / 'xtb'
    root.mkdir(parents=True, exist_ok=True)
    archive = root / URL.rsplit('/', 1)[1]
    if not archive.exists():
        data = urllib.request.urlopen(URL, timeout=60).read()
    else:
        data = archive.read_bytes()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('xTB archive SHA256 mismatch')
    archive.write_bytes(data)
    with zipfile.ZipFile(archive) as bundle:
        if any(not (root / member.filename).resolve().is_relative_to(root.resolve()) for member in bundle.infolist()):
            raise ValueError('Unsafe archive member path')
        bundle.extractall(root)
    (root / 'installation.json').write_text(json.dumps({'source': URL, 'sha256': SHA256, 'version': '6.7.1pre'}, indent=2), encoding='utf-8')
    print('xTB ready in ' + str(root))


if __name__ == '__main__':
    main()
