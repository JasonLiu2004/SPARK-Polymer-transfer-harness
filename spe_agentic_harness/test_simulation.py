"""Offline contract tests. FixtureBackend performs NO molecular simulation."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import ResearchHarness
from simulation import ENGINES, RemoteSimulationClient


def candidate():
    return {'name': 'PEO/LiTFSI interface test', 'polymer_repeat_unit_smiles': '*CCO*',
            'salt': 'LiTFSI', 'salt_concentration': {'value': 1.5, 'unit': 'mol/kg', 'basis': 'polymer mass'},
            'temperature_K': 353., 'input_origin': 'test_fixture',
            'sources': ['Synthetic test recipe, not an extracted or validated experimental sample']}


def assumptions():
    return {k: {'value': v, 'reason': 'Explicit synthetic model choice for interface testing'} for k, v in {
        'architecture': 'linear_homopolymer', 'chain_length': 30,
        'end_groups': {'left': '*C', 'right': '*C'}, 'additives': [], 'material_state': 'amorphous',
    }.items()}


def coordination_system():
    return {'fragment': {'symbols': ['O', 'H', 'H'], 'positions_angstrom': [[0, 0, 0], [.96, 0, 0], [-.24, .93, 0]],
                         'charge': 0, 'multiplicity': 1},
            'ion': {'symbols': ['Li'], 'positions_angstrom': [[0, 0, 2]], 'charge': 1, 'multiplicity': 1},
            'input_origin': 'test_fixture', 'sources': ['Synthetic geometry for protocol test only']}


class FixtureBackend:
    """Echoes labelled artificial metrics; never loaded by the real planner."""
    is_test_backend = True
    supported_pairs = frozenset((task, engine) for task, engines in ENGINES.items() for engine in engines)

    def run(self, request):
        task = request['task']
        result = {'request_id': request['request_id'], 'task': task, 'engine': request['engine'],
                  'status': 'completed', 'data_origin': 'test_fixture', 'method': 'artificial-contract-fixture',
                  'engine_version': 'fixture-v1', 'converged': True, 'temperature_K': 353.,
                  'disclaimer': 'No simulator or quantum chemistry engine was run'}
        if task == 'simulate_electrolyte':
            result['trajectory_ref'] = 'fixture://no-real-trajectory'
        elif task == 'analyze_ion_transport':
            result['metrics'] = {'conductivity': {'value': .001, 'unit': 'S/cm'}}
        elif task == 'calculate_coordination':
            result['metrics'] = {'binding_energy': {'value': -.5, 'unit': 'eV'}}
        else:
            result['metrics'] = {'density': {'value': 1.1, 'unit': 'g/cm3'}}
        return result


class SimulationTests(unittest.TestCase):
    def test_missing_inputs_assumptions_and_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp)
            incomplete = h.execute('prepare_simulation_input', {'candidate': candidate()})['data']
            self.assertEqual(incomplete['status'], 'needs_input')
            self.assertIn('chain_length', incomplete['missing'])
            self.assertEqual(h.execute('simulate_electrolyte', {'prepared_id': incomplete['record_id'], 'engine': 'pemd'})['data']['status'], 'needs_input')
            ready = h.execute('prepare_simulation_input', {'candidate': candidate(), 'assumptions': assumptions()})['data']
            self.assertEqual(ready['status'], 'schema_ready')
            self.assertFalse(ready['chemical_structure_verified'])
            self.assertEqual(len(ready['modelling_assumptions']), 5)
            self.assertEqual(h.execute('simulate_electrolyte', {'prepared_id': ready['record_id'], 'engine': 'pemd'})['data']['status'], 'unavailable')
            bad = {'candidate': candidate(), 'assumptions': {'temperature_K': {'value': 300, 'reason': 'overwrite'}}}
            self.assertEqual(h.execute('prepare_simulation_input', bad)['status'], 'error')
            self.assertEqual(h.execute('prepare_simulation_input', {'candidate': candidate(), 'assumptions': []})['status'], 'error')

    def test_pipeline_memory_project_isolation_and_fixture_label(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'memory.sqlite'
            h = ResearchHarness(Path(tmp) / 'run', knowledge_db=db, simulation_provider=FixtureBackend())
            ready = h.execute('prepare_simulation_input', {'candidate': candidate(), 'assumptions': assumptions()})['data']
            sim = h.execute('simulate_electrolyte', {'prepared_id': ready['record_id'], 'engine': 'pemd'})['data']
            result = h.execute('analyze_ion_transport', {'simulation_id': sim['record_id'], 'engine': 'seamm'})['data']
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['data_origin'], 'test_fixture')
            self.assertFalse(result['eligible_for_ranking'])
            self.assertEqual(result['parent_id'], sim['record_id'])
            restarted = ResearchHarness(Path(tmp) / 'next', knowledge_db=db)
            self.assertEqual(restarted.simulations.get(result['record_id'])['request']['task'], 'analyze_ion_transport')
            other = ResearchHarness(Path(tmp) / 'other', knowledge_db=db, project_id='different')
            self.assertEqual(other.execute('get_simulation_record', {'record_id': result['record_id']})['status'], 'error')

    def test_coordination_and_auxiliary_properties(self):
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp, simulation_provider=FixtureBackend())
            response = h.execute('calculate_coordination', {'system': coordination_system(), 'engine': 'xtb'})
            self.assertEqual(response['data']['status'], 'completed')
            bad = coordination_system()
            bad['fragment']['positions_angstrom'].pop()
            self.assertEqual(h.execute('calculate_coordination', {'system': bad, 'engine': 'xtb'})['status'], 'error')
            prepared = h.simulations.prepare(candidate(), assumptions())
            args = {'prepared_id': prepared['record_id'], 'engine': 'radonpy', 'properties': ['density']}
            self.assertEqual(h.execute('calculate_polymer_properties', args)['data']['status'], 'completed')
            args['properties'] = ['glass_transition_temperature']
            self.assertEqual(h.execute('calculate_polymer_properties', args)['status'], 'error')

    def test_wrong_result_and_units_rejected(self):
        for key, value in [('request_id', 'wrong'), ('temperature_K', 300), ('data_origin', 'experiment'),
                           ('converged', 'yes')]:
            class Bad(FixtureBackend):
                def run(self, request):
                    result = super().run(request)
                    result[key] = value
                    return result
            with tempfile.TemporaryDirectory() as tmp:
                h = ResearchHarness(tmp, simulation_provider=Bad())
                p = h.simulations.prepare(candidate(), assumptions())
                self.assertEqual(h.execute('simulate_electrolyte', {'prepared_id': p['record_id'], 'engine': 'pemd'})['status'], 'error', key)
        class BadUnits(FixtureBackend):
            def run(self, request):
                result = super().run(request)
                result['metrics']['binding_energy']['unit'] = 'S/cm'
                return result
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp, simulation_provider=BadUnits())
            self.assertEqual(h.execute('calculate_coordination', {'system': coordination_system(), 'engine': 'xtb'})['status'], 'error')

    def test_unfinished_and_nonconverged_not_analyzed(self):
        class Unfinished(FixtureBackend):
            def run(self, request):
                return {**super().run(request), 'status': 'running', 'converged': False}
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp, simulation_provider=Unfinished())
            p = h.simulations.prepare(candidate(), assumptions())
            result = h.simulations.simulate(p['record_id'], 'pemd')
            self.assertEqual(result['status'], 'not_completed')
            self.assertNotIn('metrics', result)
        class Nonconverged(FixtureBackend):
            def run(self, request):
                return {**super().run(request), 'converged': False}
        with tempfile.TemporaryDirectory() as tmp:
            h = ResearchHarness(tmp, simulation_provider=Nonconverged())
            p = h.simulations.prepare(candidate(), assumptions())
            sim = h.simulations.simulate(p['record_id'], 'pemd')
            self.assertEqual(h.simulations.analyze(sim['record_id'], 'pemd')['status'], 'needs_review')

    def test_http_adapter_serializes_and_redacts_errors(self):
        client = RemoteSimulationClient('https://example.invalid/compute', [('simulate_electrolyte', 'pemd')], token='TEST_TOKEN')
        request = {'schema_version': 'simulation.v1', 'request_id': 'a', 'task': 'simulate_electrolyte'}
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'{"status":"completed"}')) as urlopen:
            self.assertEqual(client.run(request)['status'], 'completed')
            actual = urlopen.call_args.args[0]
            self.assertEqual(json.loads(actual.data), request)
            self.assertEqual(actual.get_header('Authorization'), 'Bearer TEST_TOKEN')
        with patch('urllib.request.urlopen', side_effect=TimeoutError('TEST_TOKEN')):
            with self.assertRaises(RuntimeError) as caught:
                client.run(request)
            self.assertNotIn('TEST_TOKEN', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
