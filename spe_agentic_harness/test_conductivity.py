import tempfile
from pathlib import Path
import unittest

from harness import ResearchHarness


def fixture():
    return {'candidate': {'name': 'synthetic transport example', 'temperature_K': 300,
                         'input_origin': 'test_fixture', 'sources': ['Synthetic numbers for unit test, not a measured material']},
            'method': 'nernst_einstein', 'transport': {'complete_mobile_species': True, 'species': [
                {'name': 'Li+', 'charge_number': 1, 'concentration_mol_L': 1., 'diffusion_m2_s': 1e-11, 'source': 'synthetic'},
                {'name': 'anion', 'charge_number': -1, 'concentration_mol_L': 1., 'diffusion_m2_s': 2e-11, 'source': 'synthetic'}]}}


class PropertyTests(unittest.TestCase):
    def test_ne_units_persistence_and_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'memory.sqlite'
            h = ResearchHarness(Path(tmp) / 'a', knowledge_db=db)
            out = h.execute('predict_conductivity', fixture())
            self.assertEqual(out['status'], 'ok')
            # Independently use number density * e^2 * D / (k_B T), then S/m -> S/cm.
            expected = (1000 * 6.02214076e23 * (1.602176634e-19)**2 * 3e-11
                        / (1.380649e-23 * 300) / 100)
            self.assertAlmostEqual(out['data']['conductivity']['value'], expected, places=12)
            self.assertEqual(out['data']['data_origin'], 'derived_from_supplied_diffusivities')
            h2 = ResearchHarness(Path(tmp) / 'b', knowledge_db=db)
            self.assertEqual(len(h2.execute('query_property_results', {'text': 'synthetic'})['data']['results']), 1)
            h3 = ResearchHarness(Path(tmp) / 'c', knowledge_db=db, project_id='other')
            self.assertEqual(h3.properties.query('synthetic')['results'], [])
            self.assertEqual(h.knowledge.query('default', 'synthetic'), [])

    def test_bad_inputs_never_produce_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp)
            for change in ('negative', 'nan', 'missing_ion', 'missing_source', 'incomplete'):
                args = fixture()
                if change == 'negative': args['transport']['species'][0]['diffusion_m2_s'] = -1
                if change == 'nan': args['candidate']['temperature_K'] = float('nan')
                if change == 'missing_ion': args['transport']['species'].pop()
                if change == 'missing_source': args['transport']['species'][0]['source'] = ''
                if change == 'incomplete': args['transport']['complete_mobile_species'] = False
                self.assertEqual(h.execute('predict_conductivity', args)['status'], 'error', change)

    def test_remote_unavailable_without_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp)
            out = h.execute('predict_conductivity', {'candidate': fixture()['candidate'], 'method': 'remote_ml'})
            self.assertEqual(out['data']['status'], 'unavailable')
            self.assertIsNone(out['data']['conductivity'])
            self.assertEqual(h.properties.query('')['results'], [])

    def test_remote_binding_units_and_domain(self):
        class Provider:
            bad_binding = False
            def predict(self, request):
                return {'status': 'completed', 'request_id': 'wrong' if self.bad_binding else request['request_id'],
                        'data_origin': 'ml_prediction', 'model_version': 'fixture-1', 'calculation_method': 'fixture-regression',
                        'conductivity': {'value': .1, 'unit': 'S/m', 'temperature_K': 300},
                        'applicability': 'out_of_domain', 'uncertainty': None}
        with tempfile.TemporaryDirectory() as tmp:
            provider = Provider()
            h = ResearchHarness(tmp, property_provider=provider)
            candidate = fixture()['candidate']
            candidate.update(polymer_repeat_unit_smiles='*CCO*', salt='LiTFSI',
                             salt_concentration={'value': 1, 'unit': 'mol/kg', 'basis': 'polymer mass'}, additives=[])
            result = h.execute('predict_conductivity', {'candidate': candidate, 'method': 'remote_ml'})
            self.assertEqual(result['data']['conductivity']['value'], .001)
            self.assertFalse(result['data']['eligible_for_ranking'])
            provider.bad_binding = True
            self.assertEqual(h.execute('predict_conductivity', {'candidate': candidate, 'method': 'remote_ml'})['status'], 'error')

    def test_single_ion_fixed_charge(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp)
            args = fixture()
            args['transport']['species'].pop()
            args['transport']['fixed_charge_mol_L'] = -1.
            out = h.execute('predict_conductivity', args)
            self.assertEqual(out['status'], 'ok')

    def test_md_requires_convergence_and_no_pending_values(self):
        from conductivity import ConductivityTools
        raw = {'status': 'completed', 'request_id': 'a', 'data_origin': 'md_simulation',
               'conductivity': {'value': 1, 'unit': 'mS/cm', 'temperature_K': 300},
               'model_version': 'fixture', 'calculation_method': 'Einstein-Helfand', 'applicability': 'in_domain'}
        with self.assertRaises(ValueError): ConductivityTools._validate_remote(raw, 'a', 'remote_md', 300)
        raw['converged'] = False
        self.assertFalse(ConductivityTools._validate_remote(raw, 'a', 'remote_md', 300)['eligible_for_ranking'])
        raw['status'] = 'running'
        with self.assertRaises(ValueError): ConductivityTools._validate_remote(raw, 'a', 'remote_md', 300)


if __name__ == '__main__':
    unittest.main()
