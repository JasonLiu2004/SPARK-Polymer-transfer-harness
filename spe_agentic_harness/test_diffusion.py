import tempfile
import unittest
import numpy as np
from diffusion import analyze, run_benchmark


class DiffusionTests(unittest.TestCase):
    def test_brownian_diffusion_and_units(self):
        # Independent synthetic random walk, explicitly not a molecular simulation.
        rng = np.random.default_rng(17)
        expected = 2e-9
        dt = .1
        steps = rng.normal(size=(1000, 300, 3))*np.sqrt(2*expected/1e-6*dt)
        r = analyze(np.cumsum(steps, axis=0), dt)
        self.assertAlmostEqual(r['preliminary_D_m2_s']/expected, 1, delta=.15)
        self.assertIsNone(r['accepted_D_m2_s'])

    def test_immobile_has_no_positive_diffusion(self):
        self.assertIsNone(analyze(np.zeros((50, 2, 3)), .1)['preliminary_D_m2_s'])

    def test_ballistic_is_not_diffusive(self):
        p = np.zeros((100, 1, 3))
        p[:, 0, 0] = np.arange(100)*.01
        r = analyze(p, .1)
        self.assertFalse(r['diffusive_window_heuristic'])
        self.assertAlmostEqual(r['log_log_exponent'], 2)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError):
            analyze(np.full((50, 1, 3), np.nan), .1)
        with tempfile.TemporaryDirectory() as output:
            for duration in (True, 0, 501, 1.5):
                with self.assertRaises(ValueError):
                    run_benchmark(output, duration)


if __name__ == '__main__':
    unittest.main()
