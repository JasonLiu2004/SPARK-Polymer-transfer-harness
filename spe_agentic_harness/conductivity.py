"""Direct-result conductivity tools; no local ML/MD installation required.

Remote providers implement predict(request) -> result. PEMD/GROMACS do not
implement this protocol themselves: a hosted wrapper is still needed.
"""
import hashlib
import json
import math
import urllib.request


def positive(value, name, allow_zero=False):
    if (type(value) not in (float, int) or not math.isfinite(value)
            or value < 0 or (value == 0 and not allow_zero)):
        raise ValueError(f'{name} must be a finite positive number')
    return float(value)


class RemoteConductivityClient:
    """For an operator-selected hosted service, not an arbitrary agent URL.

No endpoint is enabled by default. The URL is the full POST endpoint.
"""
    def __init__(self, endpoint, token=None, timeout=45):
        if not endpoint.startswith('https://'):
            raise ValueError('Remote conductivity service requires HTTPS')
        self.endpoint, self.token, self.timeout = endpoint, token, timeout

    def predict(self, request):
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        req = urllib.request.Request(self.endpoint, data=json.dumps(request, allow_nan=False).encode(), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('Response too large')
            return json.loads(raw)
        except Exception:
            # Do not disclose endpoint tokens or raw server error pages.
            raise RuntimeError('Remote property request failed; no prediction was produced') from None


class ConductivityTools:
    def __init__(self, knowledge, project_id, provider=None):
        self.knowledge, self.project, self.provider = knowledge, project_id, provider
        with knowledge.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS property_results(
                id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    def capabilities(self):
        return {'methods': [
            {'method': 'nernst_einstein', 'available': True,
             'requires': 'temperature_K, complete mobile-ion species with concentration_mol_L and diffusion_m2_s',
             'meaning': 'Derived estimate from supplied diffusivities; not structure-to-property prediction or MD execution'},
            {'method': 'remote_ml', 'available': self.provider is not None},
            {'method': 'remote_md', 'available': self.provider is not None},
        ], 'remote_note': 'Configured transport is not proof of model applicability. Provider must validate each request.',
            'local_simulation_installation_required': False}

    def predict(self, candidate, method, transport=None):
        if method not in ('nernst_einstein', 'remote_ml', 'remote_md'):
            raise ValueError('Unknown conductivity method')
        if not isinstance(candidate, dict):
            raise ValueError('candidate must be an object')
        for field in ('name', 'input_origin'):
            if not isinstance(candidate.get(field), str) or not candidate[field].strip():
                raise ValueError(f'candidate.{field} is required')
        if candidate['input_origin'] not in ('literature', 'design_hypothesis', 'mixed', 'test_fixture'):
            raise ValueError('Invalid input_origin')
        temperature = positive(candidate.get('temperature_K'), 'temperature_K')
        if (not isinstance(candidate.get('sources'), list) or not candidate['sources']
                or any(not isinstance(s, str) or not s.strip() for s in candidate['sources'])):
            raise ValueError('candidate.sources must describe provenance, including hypothetical/test inputs')
        if method != 'nernst_einstein' and transport is not None:
            raise ValueError('transport is only used by nernst_einstein')
        request = {'schema_version': 'conductivity.v1', 'candidate': candidate, 'method': method}
        if transport is not None:
            request['transport'] = transport
        canonical = json.dumps(request, sort_keys=True, ensure_ascii=False, allow_nan=False)
        request_id = hashlib.sha256(canonical.encode()).hexdigest()
        request['request_id'] = request_id
        if method == 'nernst_einstein':
            result = self._nernst_einstein(temperature, transport)
        else:
            if self.provider is None:
                return {'status': 'unavailable', 'conductivity': None,
                        'reason': 'No validated hosted polymer-electrolyte provider is connected',
                        'next_action': 'Keep the property unknown; do not substitute an LLM guess or an inorganic/liquid model'}
            missing = [f for f in ('polymer_repeat_unit_smiles', 'salt', 'salt_concentration', 'additives')
                       if f not in candidate or candidate[f] is None]
            if missing:
                return {'status': 'needs_input', 'conductivity': None, 'missing': missing}
            for key in ('polymer_repeat_unit_smiles', 'salt'):
                if not isinstance(candidate[key], str) or not candidate[key].strip():
                    raise ValueError(f'candidate.{key} must be nonempty')
            concentration = candidate['salt_concentration']
            if not isinstance(concentration, dict):
                raise ValueError('salt_concentration must have value, unit and basis')
            positive(concentration.get('value'), 'salt_concentration.value')
            for key in ('unit', 'basis'):
                if not isinstance(concentration.get(key), str) or not concentration[key].strip():
                    raise ValueError(f'salt_concentration.{key} is required')
            if not isinstance(candidate['additives'], list):
                raise ValueError('additives must be an explicit list')
            raw = self.provider.predict(request)
            result = self._validate_remote(raw, request_id, method, temperature)
        result.update(request_id=request_id, candidate=candidate,
                      inputs_verified=False, review_status='unreviewed_computation')
        payload = json.dumps(result, sort_keys=True, ensure_ascii=False, allow_nan=False)
        rid = hashlib.sha256((self.project + '\n' + payload).encode()).hexdigest()
        with self.knowledge.connect() as db:
            db.execute('INSERT OR IGNORE INTO property_results(id,project,payload) VALUES(?,?,?)', (rid, self.project, payload))
        return {**result, 'property_result_id': rid}

    @staticmethod
    def _nernst_einstein(temperature, transport):
        if not isinstance(transport, dict) or not isinstance(transport.get('species'), list) or not transport['species']:
            raise ValueError('transport.species must contain all mobile ionic species')
        if transport.get('complete_mobile_species') is not True:
            raise ValueError('Explicit complete_mobile_species=true is required')
        weighted_diffusion, net_charge, charge_scale = 0., 0., 0.
        labels = set()
        for species in transport['species']:
            if not isinstance(species, dict):
                raise ValueError('Each species must be an object')
            label = species.get('name')
            if not isinstance(label, str) or not label.strip() or label in labels:
                raise ValueError('Each species needs a unique name')
            labels.add(label)
            z = species.get('charge_number')
            if type(z) is not int or z == 0:
                raise ValueError('charge_number must be a nonzero integer')
            c = positive(species.get('concentration_mol_L'), 'concentration_mol_L')
            d = positive(species.get('diffusion_m2_s'), 'diffusion_m2_s', allow_zero=True)
            if not isinstance(species.get('source'), str) or not species['source'].strip():
                raise ValueError('Each diffusivity requires a source description')
            weighted_diffusion += c * 1000 * z * z * d
            net_charge += c * z
            charge_scale += c * abs(z)
        # Fixed charges are legitimate in single-ion polymer electrolytes.
        fixed = transport.get('fixed_charge_mol_L', 0.)
        if type(fixed) not in (float, int) or not math.isfinite(fixed):
            raise ValueError('fixed_charge_mol_L must be a signed finite number')
        if abs(net_charge + fixed) > 1e-6 * max(charge_scale, abs(fixed), 1e-12):
            raise ValueError('Ion concentrations and fixed charge do not satisfy electroneutrality')
        faraday, gas_constant = 96485.33212331002, 8.31446261815324
        sigma = faraday ** 2 * weighted_diffusion / (gas_constant * temperature) / 100
        if not math.isfinite(sigma):
            raise ValueError('Conductivity overflow; check input units')
        return {'status': 'completed', 'method': 'nernst_einstein',
                'data_origin': 'derived_from_supplied_diffusivities',
                'conductivity': {'value': sigma, 'unit': 'S/cm', 'temperature_K': temperature},
                'log10_sigma_S_cm': math.log10(sigma) if sigma > 0 else None,
                'uncertainty': None, 'applicability': 'independent_ion_approximation',
                'eligible_for_ranking': False,
                'transport': transport, 'model_version': 'nernst-einstein-v1',
                'limitations': ['Ion-ion transport correlations omitted',
                                'Input provenance is recorded but not verified',
                                'Zero supplied diffusion is not proof of zero long-time conductivity']}

    @staticmethod
    def _validate_remote(raw, request_id, method, temperature):
        if not isinstance(raw, dict) or raw.get('request_id') != request_id:
            raise ValueError('Remote result request_id mismatch')
        if raw.get('status') != 'completed':
            raise ValueError('Provider did not return a completed result; no numerical value accepted')
        expected_origin = 'ml_prediction' if method == 'remote_ml' else 'md_simulation'
        if raw.get('data_origin') != expected_origin:
            raise ValueError('Remote result data_origin mismatch')
        prop = raw.get('conductivity', {})
        value = positive(prop.get('value'), 'conductivity', allow_zero=True)
        if prop.get('unit') not in ('S/cm', 'S/m', 'mS/cm'):
            raise ValueError('Unsupported conductivity unit')
        if prop.get('temperature_K') != temperature:
            raise ValueError('Remote result temperature mismatch')
        for key in ('model_version', 'calculation_method'):
            if not isinstance(raw.get(key), str) or not raw[key].strip():
                raise ValueError(f'Remote result requires {key}')
        if raw.get('applicability') not in ('in_domain', 'out_of_domain', 'unknown'):
            raise ValueError('Remote result requires applicability')
        if method == 'remote_md' and type(raw.get('converged')) is not bool:
            raise ValueError('MD result requires converged flag')
        scale = {'S/cm': 1, 'S/m': .01, 'mS/cm': .001}[prop['unit']]
        sigma = value * scale
        return {**raw, 'method': method,
                'conductivity': {'value': sigma, 'unit': 'S/cm', 'temperature_K': temperature},
                'log10_sigma_S_cm': math.log10(sigma) if sigma else None,
                'uncertainty': raw.get('uncertainty'),
                'eligible_for_ranking': raw['applicability'] == 'in_domain'
                    and (method != 'remote_md' or raw['converged'])}

    def query(self, text, limit=20):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('limit must be 1..100')
        with self.knowledge.connect() as db:
            rows = db.execute('''SELECT id,payload FROM property_results
                WHERE project=? AND instr(lower(payload),lower(?))>0
                ORDER BY rowid DESC LIMIT ?''', (self.project, text, limit)).fetchall()
        return {'results': [{'property_result_id': rid, **json.loads(payload)} for rid, payload in rows]}
