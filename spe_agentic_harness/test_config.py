import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from config import load_env


class ConfigTests(unittest.TestCase):
    def test_literals_and_environment_priority(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'LLM_MODEL': 'terminal'}, clear=True):
            path = Path(tmp) / '.env'
            path.write_text('# note\nLLM_API_KEY="a=b#c"\nLLM_MODEL=file\nLLM_BASE_URL=https://example.org/v1\nOPENALEX_API_KEY=\n', encoding='utf-8-sig')
            load_env(path)
            self.assertEqual(os.environ['LLM_API_KEY'], 'a=b#c')
            self.assertEqual(os.environ['LLM_MODEL'], 'terminal')
            self.assertNotIn('OPENALEX_API_KEY', os.environ)
            load_env(Path(tmp) / 'missing')

    def test_error_does_not_leak_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_text('LLM_API_KEY="secret', encoding='utf-8')
            with self.assertRaises(ValueError) as error:
                load_env(path)
            self.assertNotIn('secret', str(error.exception))
