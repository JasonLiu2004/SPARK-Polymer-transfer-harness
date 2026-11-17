import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import ResearchHarness
from run_xtb_example import example_system
from xtb_backend import XTBBackend, HARTREE_TO_KJMOL, discover_xtb_backend


class XTBTests(unittest.TestCase):
    def test_unsupported_system_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            backend = XTBBackend(Path(tmp) / 'unused.exe', tmp)
            system = example_system()
            system['ion']['symbols'] = ['Na']
            with patch('xtb_backend.subprocess.run') as spawn:
                with self.assertRaises(ValueError):
                    backend.run({'task': 'calculate_coordination', 'engine': 'xtb', 'payload': {'system': system}})
                spawn.assert_not_called()

    def test_real_engine_when_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            if discover_xtb_backend(tmp) is None:
                self.skipTest('Official xTB portable runtime not present')
            h = ResearchHarness(tmp)
            result = h.execute('calculate_coordination', {'system': example_system(), 'engine': 'xtb'})
            self.assertEqual(result['status'], 'ok')
            data = result['data']
            self.assertEqual(data['status'], 'completed', data)
            self.assertEqual(data['data_origin'], 'quantum_calculation')
            self.assertFalse(data['test_backend'])
            self.assertTrue(data['converged'])
            energies = data['energies_hartree']
            expected = (energies['complex'] - energies['fragment'] - energies['ion']) * HARTREE_TO_KJMOL
            self.assertAlmostEqual(data['metrics']['binding_energy']['value'], expected, places=8)
            self.assertTrue(math.isfinite(expected))
            self.assertEqual(len(data['optimized_complex']['symbols']), 10)
            for name, part in data['parts'].items():
                self.assertTrue((Path(part['artifact_dir']) / 'stdout.log').is_file())
                self.assertEqual(part['exit_code'], 0)


if __name__ == '__main__':
    unittest.main()
