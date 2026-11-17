"""Agent-facing preparation and direct-result simulation contracts.

An engine name selects a connected adapter. The harness auto-discovers its
project-managed xTB executable; other engines require an explicit provider.
Prepared inputs pass schema checks, not chemical validation.
"""
import hashlib
import json
import math

from conductivity import RemoteConductivityClient, positive
from knowledge import encoded


ENGINES = {
    'simulate_electrolyte': ('pemd', 'gromacs', 'lammps', 'matlantis'),
    'analyze_ion_transport': ('pemd', 'gromacs', 'lammps', 'seamm', 'matlantis'),
    'calculate_coordination': ('xtb', 'cp2k', 'matlantis'),
    'calculate_polymer_properties': ('radonpy', 'pemd', 'matlantis'),
}
REQUIRED = ('name', 'polymer_repeat_unit_smiles', 'architecture', 'chain_length',
            'end_groups', 'salt', 'salt_concentration', 'temperature_K',
            'additives', 'material_state', 'input_origin', 'sources')
ASSUMABLE = set(REQUIRED) - {'name', 'polymer_repeat_unit_smiles', 'input_origin', 'sources'}
METRIC_UNITS = {
    'conductivity': ('S/cm', 'S/m', 'mS/cm'),
    'li_diffusion': ('m2/s',), 'anion_diffusion': ('m2/s',),
    'coordination_number': ('dimensionless',), 'residence_time': ('ps', 'ns'),
    'binding_energy': ('eV', 'kJ/mol', 'hartree'),
    'density': ('g/cm3', 'kg/m3'), 'glass_transition_temperature': ('K',),
    'young_modulus': ('Pa', 'MPa', 'GPa'), 'heat_capacity': ('J/(kg K)',),
}
TASK_METRICS = {
    'analyze_ion_transport': {'conductivity', 'li_diffusion', 'anion_diffusion', 'coordination_number', 'residence_time'},
    'calculate_coordination': {'binding_energy', 'coordination_number'},
    'calculate_polymer_properties': {'density', 'glass_transition_temperature', 'young_modulus', 'heat_capacity'},
}


class RemoteSimulationClient:
    """Operator-created client for our simulation.v1 HTTP wrapper protocol.

supported_pairs is a verified deployment manifest, e.g.
{('simulate_electrolyte', 'pemd'), ('analyze_ion_transport', 'pemd')}.
This is NOT a native PEMD/GROMACS/Matlantis API.
"""
    is_test_backend = False

    def __init__(self, endpoint, supported_pairs, token=None, timeout=45):
        self.supported_pairs = frozenset(tuple(pair) for pair in supported_pairs)
        if any(engine not in ENGINES.get(task, ()) for task, engine in self.supported_pairs):
            raise ValueError('Unsupported task/engine pair')
        self.http = RemoteConductivityClient(endpoint, token, timeout)

    def run(self, request):
        return self.http.predict(request)


class SimulationTools:
    def __init__(self, knowledge, project, provider=None):
        self.knowledge, self.project, self.provider = knowledge, project, provider
        with knowledge.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS simulation_records(
                id TEXT PRIMARY KEY, project TEXT NOT NULL, kind TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    def _save(self, kind, result):
        payload = encoded(result)
        rid = hashlib.sha256((self.project + '\n' + kind + '\n' + payload).encode()).hexdigest()
        with self.knowledge.connect() as db:
            db.execute('INSERT OR IGNORE INTO simulation_records(id,project,kind,payload) VALUES(?,?,?,?)',
                       (rid, self.project, kind, payload))
        return {**result, 'record_id': rid}

    def get(self, record_id):
        with self.knowledge.connect() as db:
            row = db.execute('SELECT kind,payload FROM simulation_records WHERE id=? AND project=?',
                             (record_id, self.project)).fetchone()
        if row is None:
            raise ValueError('Simulation record not found in this project')
        return {**json.loads(row[1]), 'record_id': record_id, 'kind': row[0]}

    def capabilities(self):
        pairs = getattr(self.provider, 'supported_pairs', ())
        return {'prepare_simulation_input': 'available',
                'test_backend': bool(getattr(self.provider, 'is_test_backend', False)),
                'services': [{'task': task, 'engine': engine, 'connected': (task, engine) in pairs}
                             for task, engines in ENGINES.items() for engine in engines],
                'note': 'Connected is an adapter declaration, not an accuracy benchmark. Project-managed xTB is auto-discovered when present.'}

    def prepare(self, candidate, assumptions=None):
        assumptions = {} if assumptions is None else assumptions
        if not isinstance(candidate, dict) or not isinstance(assumptions, dict):
            raise ValueError('candidate and assumptions must be objects')
        supplied = json.loads(encoded(candidate))
        merged = json.loads(encoded(candidate))
        for key, claim in assumptions.items():
            if key not in ASSUMABLE:
                raise ValueError(f'Cannot fill {key} as an automatic modelling assumption')
            if key in merged and merged[key] is not None:
                raise ValueError(f'Assumption cannot overwrite supplied {key}')
            if (not isinstance(claim, dict) or 'value' not in claim
                    or not isinstance(claim.get('reason'), str) or not claim['reason'].strip()):
                raise ValueError('Each assumption requires value and reason')
            merged[key] = claim['value']
        missing = [k for k in REQUIRED if k not in merged or merged[k] is None]
        issues = []
        for key in ('name', 'polymer_repeat_unit_smiles', 'architecture', 'salt', 'material_state'):
            if key not in missing and (not isinstance(merged[key], str) or not merged[key].strip()):
                issues.append(f'{key}: nonempty string required')
        if 'temperature_K' not in missing:
            try:
                positive(merged['temperature_K'], 'temperature_K')
            except ValueError as exc:
                issues.append(str(exc))
        if 'chain_length' not in missing and (type(merged['chain_length']) is not int or merged['chain_length'] < 1):
            issues.append('chain_length: positive integer required')
        if 'end_groups' not in missing:
            ends = merged['end_groups']
            if not isinstance(ends, dict) or any(not isinstance(ends.get(k), str) or not ends[k].strip() for k in ('left', 'right')):
                issues.append('end_groups: left and right structures required')
        if 'additives' not in missing:
            if not isinstance(merged['additives'], list):
                issues.append('additives: explicit list required; [] means explicitly absent')
            else:
                for additive in merged['additives']:
                    if not isinstance(additive, dict) or not additive.get('name') or not isinstance(additive.get('amount'), dict):
                        issues.append('Each additive requires name and amount with value/unit/basis')
                    else:
                        issues.extend(self._concentration_issues(additive['amount'], 'additive.amount'))
        if 'salt_concentration' not in missing:
            issues.extend(self._concentration_issues(merged['salt_concentration'], 'salt_concentration'))
        if 'input_origin' not in missing and merged['input_origin'] not in ('literature', 'mixed', 'design_hypothesis', 'test_fixture'):
            issues.append('input_origin: unknown origin type')
        if 'sources' not in missing and (not isinstance(merged['sources'], list) or not merged['sources']
                or any(not isinstance(x, str) or not x.strip() for x in merged['sources'])):
            issues.append('sources: nonempty list of provenance strings required')
        if assumptions and merged.get('input_origin') == 'literature':
            merged['input_origin'] = 'mixed'
        return self._save('prepared_input', {
            'status': 'needs_input' if missing or issues else 'schema_ready',
            'candidate': merged, 'supplied_inputs': supplied, 'modelling_assumptions': assumptions,
            'missing': missing, 'issues': issues,
            'chemical_structure_verified': False, 'evidence_verified': False,
            'backend_checks_required': ['SMILES validity and connection sites', 'force-field/element coverage',
                                        'concentration-to-particle-count conversion', 'phase and topology compatibility'],
        })

    @staticmethod
    def _concentration_issues(amount, label):
        if not isinstance(amount, dict):
            return [label + ': value/unit/basis required']
        issues = []
        try:
            positive(amount.get('value'), label + '.value')
        except ValueError as exc:
            issues.append(str(exc))
        for k in ('unit', 'basis'):
            if not isinstance(amount.get(k), str) or not amount[k].strip():
                issues.append(label + '.' + k + ': required')
        return issues

    def simulate(self, prepared_id, engine):
        prepared = self.get(prepared_id)
        if prepared['kind'] != 'prepared_input':
            raise ValueError('Expected a prepared input record')
        if prepared['status'] != 'schema_ready':
            return {'status': 'needs_input', 'prepared_id': prepared_id,
                    'missing': prepared['missing'], 'issues': prepared['issues']}
        return self._run('simulate_electrolyte', engine, {'prepared_input': prepared}, prepared_id)

    def analyze(self, simulation_id, engine):
        simulation = self.get(simulation_id)
        if simulation['kind'] != 'simulate_electrolyte' or simulation['status'] != 'completed':
            raise ValueError('Expected a completed simulation record')
        if not simulation['converged']:
            return {'status': 'needs_review', 'simulation_id': simulation_id, 'reason': 'Simulation has not converged'}
        # Pass only the saved source record, not an arbitrary trajectory URL supplied by the agent.
        return self._run('analyze_ion_transport', engine, {'simulation': simulation}, simulation_id)

    def polymer(self, prepared_id, engine, properties):
        if not properties or any(p not in TASK_METRICS['calculate_polymer_properties'] for p in properties):
            raise ValueError('Unsupported polymer property requested')
        prepared = self.get(prepared_id)
        if prepared['kind'] != 'prepared_input':
            raise ValueError('Expected prepared input')
        # v1 intentionally reuses the electrolyte recipe; backend must retain its composition.
        if prepared['status'] != 'schema_ready':
            return {'status': 'needs_input', 'missing': prepared['missing'], 'issues': prepared['issues']}
        return self._run('calculate_polymer_properties', engine,
                         {'prepared_input': prepared, 'properties': properties}, prepared_id)

    def coordination(self, system, engine):
        if not isinstance(system, dict):
            raise ValueError('system must be an object')
        for name in ('fragment', 'ion'):
            geometry = system.get(name, {})
            symbols, positions = geometry.get('symbols'), geometry.get('positions_angstrom')
            if (not isinstance(symbols, list) or not symbols or not isinstance(positions, list)
                    or len(symbols) != len(positions)):
                raise ValueError(f'{name} requires matching symbols and positions_angstrom')
            if any(not isinstance(s, str) or not s.isalpha() or len(s) > 2 for s in symbols):
                raise ValueError('Invalid element symbol format; backend must validate elements')
            if any(not isinstance(p, list) or len(p) != 3
                   or any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in positions):
                raise ValueError('Atomic positions must be finite three-dimensional coordinates')
            if type(geometry.get('charge')) is not int or type(geometry.get('multiplicity')) is not int or geometry['multiplicity'] < 1:
                raise ValueError('Each fragment requires integer charge and positive spin multiplicity')
        if system.get('input_origin') not in ('literature', 'mixed', 'design_hypothesis', 'test_fixture'):
            raise ValueError('system.input_origin is required')
        if not isinstance(system.get('sources'), list) or not system['sources'] or any(not isinstance(s, str) or not s.strip() for s in system['sources']):
            raise ValueError('system.sources is required')
        return self._run('calculate_coordination', engine, {'system': system}, None)

    def _run(self, task, engine, payload, parent_id):
        if engine not in ENGINES[task]:
            raise ValueError('Unsupported engine for this task')
        if (task, engine) not in getattr(self.provider, 'supported_pairs', ()):
            return {'status': 'unavailable', 'task': task, 'engine': engine,
                    'reason': 'No adapter connected for this task/engine', 'result': None}
        request = {'schema_version': 'simulation.v1', 'task': task, 'engine': engine, 'payload': payload}
        request['request_id'] = hashlib.sha256(encoded(request).encode()).hexdigest()
        try:
            raw = self.provider.run(request)
        except Exception:
            return {'status': 'backend_error', 'task': task, 'engine': engine,
                    'reason': 'Compute service did not return a result', 'result': None}
        if not isinstance(raw, dict) or raw.get('request_id') != request['request_id'] or raw.get('task') != task or raw.get('engine') != engine:
            raise ValueError('Result request/task/engine mismatch')
        encoded(raw)  # Reject NaN, infinity and unserializable values before persistence.
        if raw.get('status') in ('unavailable', 'needs_input'):
            return {'status': raw['status'], 'reason': str(raw.get('reason', 'Provider cannot run this request')),
                    'task': task, 'engine': engine, 'result': None}
        if raw.get('status') == 'failed':
            return {'status': 'failed', 'task': task, 'engine': engine, 'result': None,
                    'artifact_dir': raw.get('artifact_dir'), 'error': raw.get('error')}
        if raw.get('status') != 'completed':
            return {'status': 'not_completed', 'task': task, 'engine': engine, 'result': None,
                    'reason': 'Direct-result adapter received no completed calculation; do not repeat-submit automatically'}
        expected_origin = {'simulate_electrolyte': 'md_simulation', 'analyze_ion_transport': 'trajectory_analysis',
                           'calculate_coordination': 'quantum_calculation' if engine in ('xtb', 'cp2k') else 'ml_potential_calculation',
                           'calculate_polymer_properties': 'simulation_property'}[task]
        test_backend = bool(getattr(self.provider, 'is_test_backend', False))
        if raw.get('data_origin') != ('test_fixture' if test_backend else expected_origin):
            raise ValueError('Backend data_origin mismatch')
        for key in ('method', 'engine_version'):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f'Result requires {key}')
        if type(raw.get('converged')) is not bool:
            raise ValueError('Result requires convergence flag')
        if task == 'simulate_electrolyte':
            if not isinstance(raw.get('trajectory_ref'), str) or not raw['trajectory_ref'].strip():
                raise ValueError('Simulation requires a backend trajectory reference')
        else:
            metrics = raw.get('metrics')
            if not isinstance(metrics, dict) or not metrics:
                raise ValueError('Analysis requires named metrics')
            for name, metric in metrics.items():
                if name not in TASK_METRICS[task] or not isinstance(metric, dict) or metric.get('unit') not in METRIC_UNITS[name]:
                    raise ValueError('Unsupported metric or unit')
                value = metric.get('value')
                if type(value) not in (int, float) or not math.isfinite(value) or (name != 'binding_energy' and value < 0):
                    raise ValueError('Invalid property value')
            if task == 'calculate_polymer_properties' and not set(payload['properties']) <= set(metrics):
                raise ValueError('Requested properties missing from completed result')
        candidate = payload.get('prepared_input', {}).get('candidate')
        if candidate is None and task == 'analyze_ion_transport':
            candidate = payload['simulation'].get('candidate')
        if candidate and raw.get('temperature_K') != candidate['temperature_K']:
            raise ValueError('Result temperature differs from prepared conditions')
        return self._save(task, {**raw, 'parent_id': parent_id, 'candidate': candidate,
                               'request': request, 'test_backend': test_backend,
                               'eligible_for_ranking': False, 'review_status': 'unreviewed_computation'})
