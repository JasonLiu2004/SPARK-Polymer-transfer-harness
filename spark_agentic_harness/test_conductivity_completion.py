import tempfile,unittest
from pathlib import Path
import numpy as np
from conductivity_completion import from_resistance,analyze_trajectory

class CompletionTests(unittest.TestCase):
    def test_geometry_units_and_resistance_type(self):
        kw=dict(sample='fixture',source='synthetic unit test',thickness_um=100,area_cm2=1,resistance_ohm=100,temperature_K=298.15,resistance_kind='electrolyte_bulk')
        self.assertAlmostEqual(from_resistance(**kw)['sigma_S_cm'],1e-4)
        with self.assertRaises(ValueError):from_resistance(**{**kw,'resistance_kind':'charge_transfer'})
        with self.assertRaises(ValueError):from_resistance(**{**kw,'thickness_um':float('nan')})

    def test_collective_correlations_cancel_for_bound_pair(self):
        # Equal displacements of opposite charges: finite self diffusion, zero charge transport.
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'bound_pair.npz';rng=np.random.default_rng(4)
            x=np.cumsum(rng.normal(size=(201,1,3)),axis=0)
            np.savez(path,positions_nm=np.repeat(x,2,axis=1),time_ps=np.arange(201),charge_numbers=[1,-1],volume_nm3=10)
            kw=dict(trajectory_path=str(path),sample='bound pair fixture',source='synthetic correlated random walk',temperature_K=300,fit_start_ps=10,fit_end_ps=40,unwrapped=True,complete_charge_carriers=True)
            r=analyze_trajectory(**kw)
            self.assertEqual(r['sigma_einstein_helfand_S_cm'],0)
            self.assertGreater(r['sigma_nernst_einstein_S_cm'],0)
            self.assertFalse(r['eligible_for_ranking'])
            with self.assertRaises(ValueError):analyze_trajectory(**{**kw,'unwrapped':False})
            with self.assertRaises(ValueError):analyze_trajectory(**{**kw,'fit_end_ps':200})

if __name__=='__main__':unittest.main()
