"""Provider-neutral tool registry and run context for research planners.

The planner chooses actions. This harness validates arguments, executes tools,
shares artifacts/corpora and enforces tool/model-call budgets.
"""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

from curator import Corpus, run, validate
from online import discover, download_pdf
from scope import screen
from knowledge import KnowledgeStore
from download_errors import DownloadError
from conductivity import ConductivityTools
from simulation import SimulationTools
from xtb_backend import discover_xtb_backend
from diffusion import run_benchmark, RUNTIME, BACKEND_BLOCKED_REASON


def spec(name, description, properties, required):
    return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties,
                           'required': required, 'additionalProperties': False}}}


STRING = {'type': 'string'}
INTEGER = {'type': 'integer'}
TOOLS = [
    spec('run_diffusion_benchmark', 'Run real OpenMM MD then compute Li/Cl self-diffusion from multi-origin MSD. ONLY aqueous LiCl at 300 K, NOT a polymer candidate prediction. Returns preliminary values and saved trajectories; short single runs are not ranking evidence. CPU job can take several minutes.',
         {'production_ps': INTEGER, 'seed': INTEGER}, []),
    spec('get_simulation_capabilities', 'List simulation tasks, engines and connected adapters. An engine name alone does not mean it is installed or available.', {}, []),
    spec('prepare_simulation_input', 'Save a candidate recipe with explicit modelling assumptions. Returns schema_ready or needs_input and record_id. This does not validate chemical structures or run MD.',
         {'candidate': {'type': 'object', 'description': 'Fields: name, polymer_repeat_unit_smiles, architecture, chain_length (integer degree of polymerization), end_groups {left,right}, salt, salt_concentration {value,unit,basis}, temperature_K, additives [{name,amount:{value,unit,basis}}], material_state, input_origin (literature/mixed/design_hypothesis/test_fixture), sources [strings]. Missing fields are reported, never silently defaulted.'},
          'assumptions': {'type': 'object', 'description': 'Optional missing field -> {value,reason}. May fill modelling choices, never overwrite supplied values or invent the polymer structure.'}}, ['candidate']),
    spec('simulate_electrolyte', 'Run a hosted simulation using a saved schema_ready recipe. Directly returns result or explicit unavailable/not_completed. Does not install local programs.',
         {'prepared_id': STRING, 'engine': {'type': 'string', 'enum': ['pemd', 'gromacs', 'lammps', 'matlantis']}}, ['prepared_id', 'engine']),
    spec('analyze_ion_transport', 'Analyze the trajectory of a saved completed, converged simulation. Returns transport metrics with method and provenance.',
         {'simulation_id': STRING, 'engine': {'type': 'string', 'enum': ['pemd', 'gromacs', 'lammps', 'seamm', 'matlantis']}}, ['simulation_id', 'engine']),
    spec('calculate_coordination', 'Calculate fragment-ion interactions. Project-managed xTB is auto-discovered: neutral singlet fragment (2..64 atoms, H/Li/C/N/O/F/P/S/Cl) plus one singlet Li+, gas-phase GFN2 optimization. Other engines need hosted adapters. Binding energy is not bulk conductivity.',
         {'system': {'type': 'object', 'description': 'fragment and ion each require symbols [element], positions_angstrom [[x,y,z]], integer charge and positive integer multiplicity. Also requires input_origin and sources [strings]. Coordinates share one frame. Backend validates chemistry and constructs/optimizes the complex.'},
          'engine': {'type': 'string', 'enum': ['xtb', 'cp2k', 'matlantis']}}, ['system', 'engine']),
    spec('calculate_polymer_properties', 'Calculate requested auxiliary properties for a prepared recipe. Preserve its composition; do not silently replace the electrolyte with a neat polymer.',
         {'prepared_id': STRING, 'engine': {'type': 'string', 'enum': ['radonpy', 'pemd', 'matlantis']},
          'properties': {'type': 'array', 'items': {'type': 'string', 'enum': ['density', 'glass_transition_temperature', 'young_modulus', 'heat_capacity']}}}, ['prepared_id', 'engine', 'properties']),
    spec('get_simulation_record', 'Retrieve a prepared input or computed result from project memory, including assumptions and original request.', {'record_id': STRING}, ['record_id']),
    spec('get_property_capabilities', 'Check which conductivity methods are connected before requesting prediction. No local simulator is required.',
         {}, []),
    spec('predict_conductivity', 'Return conductivity directly. nernst_einstein calculates from supplied diffusivities, not polymer structure. remote_ml/remote_md require a connected hosted provider. Preserve hypothetical inputs and never invent diffusivities.',
         {'method': {'type': 'string', 'enum': ['nernst_einstein', 'remote_ml', 'remote_md']},
          'candidate': {'type': 'object', 'description': 'Required: name, temperature_K, input_origin (literature/design_hypothesis/mixed/test_fixture), sources (nonempty provenance list). Remote methods additionally require polymer_repeat_unit_smiles, salt, salt_concentration with value/unit/basis, additives (explicit list, [] if absent).',
                        'properties': {'name': STRING, 'temperature_K': {'type': 'number'},
                                       'input_origin': STRING, 'sources': {'type': 'array', 'items': STRING},
                                       'polymer_repeat_unit_smiles': STRING, 'salt': STRING,
                                       'salt_concentration': {'type': 'object'}, 'additives': {'type': 'array', 'items': {'type': 'object'}}},
                        'required': ['name', 'temperature_K', 'input_origin', 'sources']},
          'transport': {'type': 'object', 'description': 'For NE only: complete_mobile_species=true, species=[{name,charge_number,concentration_mol_L,diffusion_m2_s,source}], optional signed fixed_charge_mol_L for immobile polymer charges. All diffusivities at candidate temperature; species list must include every mobile ion.'}},
         ['candidate', 'method']),
    spec('query_property_results', 'Query persisted computations in this project, separate from literature measurements. Results are unreviewed.',
         {'text': STRING, 'limit': INTEGER}, ['text']),
    spec('query_knowledge', 'Query project extraction assertions; returned claims are unreviewed, not verified facts.',
         {'text': STRING, 'limit': INTEGER}, ['text']),
    spec('get_knowledge_snapshot', 'Retrieve original records, evidence, issues and provenance.',
         {'snapshot_id': STRING}, ['snapshot_id']),
    spec('search_literature', 'Search OpenAlex metadata; returns papers, not verified material candidates.',
         {'query': STRING, 'limit': INTEGER}, ['query']),
    spec('screen_candidates', 'Apply transparent polymer scope rules; structure clues are hypotheses. Keep manual-review papers available.',
         {'papers': {'type': 'array', 'items': {'type': 'object'}}}, ['papers']),
    spec('fetch_pdf', 'Download a supplied public PDF URL and preserve provenance.',
         {'url': STRING}, ['url']),
    spec('open_corpus', 'Open one paper and its SI PDFs as an isolated corpus. Returns corpus_id and page counts.',
         {'paths': {'type': 'array', 'items': STRING}}, ['paths']),
    spec('search_evidence', 'Search pages within an opened corpus.',
         {'corpus_id': STRING, 'query': STRING}, ['corpus_id', 'query']),
    spec('read_evidence', 'Read a source page within an opened corpus.',
         {'corpus_id': STRING, 'source': STRING, 'page': INTEGER}, ['corpus_id', 'source', 'page']),
    spec('validate_records', 'Check records against evidence observed by this harness; semantic validity is not established by quote matching.',
         {'corpus_id': STRING, 'records': {'type': 'array', 'items': {'type': 'object'}}}, ['corpus_id', 'records']),
    spec('extract_records', 'Delegate extraction of an opened corpus to the Curator model loop. Consumes shared model budget.',
         {'corpus_id': STRING, 'max_calls': INTEGER}, ['corpus_id']),
]


def check_args(definition, arguments):
    if not isinstance(arguments, dict):
        raise ValueError('Arguments must be an object')
    schema = definition['function']['parameters']
    if set(arguments) - set(schema['properties']):
        raise ValueError('Unknown argument')
    if set(schema['required']) - set(arguments):
        raise ValueError('Missing required argument')
    def matches(value, rule):
        if 'enum' in rule and value not in rule['enum']:
            return False
        kind = rule['type']
        if kind == 'string':
            return isinstance(value, str) and bool(value.strip())
        if kind == 'integer':
            return type(value) is int
        if kind == 'number':
            return type(value) in (int, float) and math.isfinite(value)
        if kind == 'boolean':
            return type(value) is bool
        if kind == 'object':
            if not isinstance(value, dict) or set(rule.get('required', [])) - set(value):
                return False
            props = rule.get('properties', {})
            if rule.get('additionalProperties') is False and set(value) - set(props):
                return False
            return all(matches(v, props[k]) for k, v in value.items() if k in props)
        if kind == 'array':
            return isinstance(value, list) and all(matches(v, rule['items']) for v in value)
        return False
    for key, value in arguments.items():
        if not matches(value, schema['properties'][key]):
            raise ValueError(f'Invalid argument type/value: {key}')


class ResearchHarness:
    def __init__(self, output_dir, client=None, scope_file=None, max_tool_calls=50, max_model_calls=30,
                 knowledge_db=None, project_id='default', policy_version='curator-v1', property_provider=None,
                 simulation_provider=None):
        self.output = Path(output_dir).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        if any(self.output.iterdir()):
            raise ValueError('Use an empty harness output directory')
        if max_tool_calls < 1 or max_model_calls < 1:
            raise ValueError('Budgets must be positive')
        self.client = client
        self.project_id, self.policy_version = project_id, policy_version
        self.knowledge = KnowledgeStore(knowledge_db or self.output / 'knowledge.sqlite')
        self.properties = ConductivityTools(self.knowledge, project_id, property_provider)
        if simulation_provider is None:
            simulation_provider = discover_xtb_backend(self.output / 'xtb_calculations')
        self.simulations = SimulationTools(self.knowledge, project_id, simulation_provider)
        self.config = json.loads(Path(scope_file or Path(__file__).with_name('scope.json')).read_text(encoding='utf-8-sig'))
        self.max_tool_calls, self.max_model_calls = max_tool_calls, max_model_calls
        self.tool_calls = self.model_calls = 0
        self.corpora, self.observed, self.downloads = {}, {}, {}
        (self.output / 'scope.json').write_text(json.dumps(self.config, ensure_ascii=False, indent=2), encoding='utf-8')

    def definitions(self):
        # Compatible shape for function-calling APIs; framework adapters may transform it.
        return json.loads(json.dumps(TOOLS))

    def execute(self, name, arguments):
        started = time.monotonic()
        reply = {'tool': name, 'status': 'error', 'data': None, 'error': None}
        try:
            if self.tool_calls >= self.max_tool_calls:
                raise ValueError('Tool-call budget exhausted')
            self.tool_calls += 1
            definition = next((s for s in TOOLS if s['function']['name'] == name), None)
            if definition is None:
                raise ValueError('Unknown tool')
            check_args(definition, arguments)
            reply['data'] = self._dispatch(name, arguments)
            reply['status'] = 'ok'
        except DownloadError as exc:
            reply['error'] = exc.record
        except Exception as exc:
            reply['error'] = {'type': type(exc).__name__, 'message': str(exc)}
        reply['usage'] = {'elapsed_seconds': round(time.monotonic() - started, 3),
                          'tool_calls': self.tool_calls, 'model_calls': self.model_calls,
                          'remaining_model_calls': self.max_model_calls - self.model_calls}
        event = {'at': datetime.now(timezone.utc).isoformat(), 'arguments': arguments, **reply}
        with (self.output / 'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')
        return reply

    def _dispatch(self, name, args):
        if name == 'run_diffusion_benchmark':
            result = run_benchmark(self.output, **args)
            return self.simulations._save('diffusion_benchmark', result)
        if name == 'get_simulation_capabilities':
            result = self.simulations.capabilities()
            result['services'].append({'task': 'run_diffusion_benchmark', 'engine': 'openmm',
                                       'connected': (RUNTIME / 'openmm').is_dir() and not BACKEND_BLOCKED_REASON,
                                       'unavailable_reason': BACKEND_BLOCKED_REASON,
                                       'scope': 'aqueous LiCl benchmark only'})
            return result
        if name == 'prepare_simulation_input':
            return self.simulations.prepare(args['candidate'], args.get('assumptions'))
        if name == 'simulate_electrolyte':
            return self.simulations.simulate(args['prepared_id'], args['engine'])
        if name == 'analyze_ion_transport':
            return self.simulations.analyze(args['simulation_id'], args['engine'])
        if name == 'calculate_coordination':
            return self.simulations.coordination(args['system'], args['engine'])
        if name == 'calculate_polymer_properties':
            return self.simulations.polymer(args['prepared_id'], args['engine'], args['properties'])
        if name == 'get_simulation_record':
            return self.simulations.get(args['record_id'])
        if name == 'get_property_capabilities':
            return self.properties.capabilities()
        if name == 'predict_conductivity':
            return self.properties.predict(args['candidate'], args['method'], args.get('transport'))
        if name == 'query_property_results':
            return self.properties.query(args['text'], args.get('limit', 20))
        if name == 'query_knowledge':
            return {'assertions': self.knowledge.query(self.project_id, args['text'], args.get('limit', 20))}
        if name == 'get_knowledge_snapshot':
            return self.knowledge.get(self.project_id, args['snapshot_id'])
        if name == 'search_literature':
            limit = args.get('limit', 10)
            if not 1 <= limit <= 100:
                raise ValueError('Search limit must be between 1 and 100')
            return {'papers': discover(args['query'], limit)}
        if name == 'screen_candidates':
            return {'papers': [{**p, 'screening': screen(p, self.config)} for p in args['papers']]}
        if name == 'fetch_pdf':
            path, provenance = download_pdf(args['url'], self.output / 'downloads')
            self.downloads[str(path.resolve())] = provenance
            return {'path': str(path), 'provenance': provenance}
        if name == 'open_corpus':
            if not args['paths']:
                raise ValueError('At least one PDF is required')
            corpus = Corpus(args['paths'])
            for source in corpus.sources:
                source.update(self.downloads.get(source['path'], {}))
                source['page_count'] = sum(k[0] == source['source'] for k in corpus.pages)
            cid = f'C{len(self.corpora) + 1}'
            self.corpora[cid], self.observed[cid] = corpus, {}
            return {'corpus_id': cid, 'sources': corpus.sources}
        cid = args['corpus_id']
        if cid not in self.corpora:
            raise ValueError('Unknown corpus_id; call open_corpus first')
        corpus = self.corpora[cid]
        if name in ('search_evidence', 'read_evidence'):
            pages = corpus.search(args['query']) if name == 'search_evidence' else [corpus.page(args['source'], args['page'])]
            for page in pages:
                self.observed[cid][(page['source'], page['page'])] = page['text']
            return {'pages': pages}
        if name == 'validate_records':
            issues, normalized = validate(args['records'], self.observed[cid])
            return {'issues': issues, 'normalized': normalized}
        if name == 'extract_records':
            if self.client is None:
                raise ValueError('Configure a Curator client before extraction')
            requested = args.get('max_calls', 6)
            if requested < 1:
                raise ValueError('max_calls must be positive')
            budget = min(requested, self.max_model_calls - self.model_calls)
            if budget < 1:
                raise ValueError('Model-call budget exhausted')
            def counted(state):
                self.model_calls += 1
                return self.client(state)
            path = self.output / f'extraction_{self.tool_calls:03d}'
            result = run(corpus, counted, path, budget)
            from curator import SYSTEM
            import hashlib
            saved = self.knowledge.ingest(self.project_id, result, {
                'policy_version': self.policy_version, 'model': getattr(self.client, 'model', 'injected-client'),
                'prompt_sha256': hashlib.sha256(SYSTEM.encode()).hexdigest(),
                'max_calls': budget, 'artifact': str(path / 'result.json')})
            return {'result': result, 'artifact': str(path / 'result.json'), **saved}
        raise ValueError('Unimplemented tool')
