"""Load literal KEY=value settings from this project's .env without overwrites."""
import os
from pathlib import Path

ALLOWED = {'LLM_API_KEY', 'LLM_BASE_URL', 'LLM_MODEL', 'OPENALEX_API_KEY'}


def load_env(path=None):
    path = Path(path) if path else Path(__file__).resolve().parent.parent / '.env'
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            raise ValueError(f'Invalid .env format on line {number}; expected KEY=value')
        key, value = (part.strip() for part in line.split('=', 1))
        if key not in ALLOWED:
            continue
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'Unclosed .env quote on line {number}')
            value = value[1:-1]
        if value:
            os.environ.setdefault(key, value)
