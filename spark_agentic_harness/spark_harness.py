"""SPARK archived world state + shared research tools; original package is read-only."""
import hashlib
import json
from pathlib import Path
import sys
import re
import copy
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent/'spe_agentic_harness'))
from harness import ResearchHarness, spec, check_args
from scope import screen
from conductivity_completion import lookup_archive, search_legacy, from_resistance, analyze_trajectory

SOURCE = ROOT.parent/'SPARK_selected3_seed_shareable_20260807'/'SPARK_selected3_seed_shareable_20260807'
EXTRA = [
    spec('lookup_spark_conductivity','Read three archived ML predictions for an EXACT candidate_id obtained from spark_candidates. Not a measured value or new inference. Retains abstention and uncertainty.',{'candidate_id':{'type':'string'}},['candidate_id']),
    spec('search_legacy_conductivity','Search the original 3469-row extraction CSV by title/polymer/salt words. Returns raw fields and source hash. Sample/units/PDF verification required before use.',{'query':{'type':'string'},'limit':{'type':'integer'}},['query']),
    spec('conductivity_from_resistance','Compute sigma=L/(R_bulk*A) for one sample, with explicit units and source. Does not fit impedance spectra or verify the chosen resistance.',
         {'sample':{'type':'string'},'source':{'type':'string'},'thickness_um':{'type':'number'},'area_cm2':{'type':'number'},'resistance_ohm':{'type':'number'},'temperature_K':{'type':'number'},'resistance_kind':{'type':'string','enum':['electrolyte_bulk']}},
         ['sample','source','thickness_um','area_cm2','resistance_ohm','temperature_K','resistance_kind']),
    spec('conductivity_from_trajectory','Postprocess existing constant-volume MD: collective Einstein-Helfand conductivity including ion correlations and NE comparison. No MD is launched. NPZ: positions_nm [frames,carriers,3], time_ps, charge_numbers [carriers], scalar volume_nm3. Carrier COMs, all net charged groups, unwrapped coordinates. Preliminary only.',
         {'trajectory_path':{'type':'string'},'sample':{'type':'string'},'source':{'type':'string'},'temperature_K':{'type':'number'},'fit_start_ps':{'type':'number'},'fit_end_ps':{'type':'number'},'unwrapped':{'type':'boolean'},'complete_charge_carriers':{'type':'boolean'}},
         ['trajectory_path','sample','source','temperature_K','fit_start_ps','fit_end_ps','unwrapped','complete_charge_carriers']),
    spec('read_application_paper','Read a paper title/abstract from the configured local catalog by ID. Returns no silver labels or baseline predictions.',
         {'paper_id':{'type':'string'}},['paper_id']),
    spec('classify_application','Use an LLM to classify an observed paper as SPE/non-SPE/uncertain, with independent transfer route. Consumes one shared model call. Non-SPE does not mean reject. Exact quotes are checked, not scientific truth.',
         {'paper_id':{'type':'string'}},['paper_id']),
    spec('spark_screen_search', 'Screen saved search metadata by paper IDs. Never transcribe or rewrite abstracts. Explicit reviews/perspectives are background. Metadata screening does not validate suitability.',
         {'paper_ids':{'type':'array','items':{'type':'string'}}}, ['paper_ids']),
    spec('spark_capabilities', 'Inspect archived SPARK capabilities and missing model artifacts.', {}, []),
    spec('spark_candidates', 'Read archived 2024 complete-panel rankings. These are coarse motifs, not recipes or new inference. Filtering does not recompute ranks. Includes abstention and provenance.',
         {'seed': {'type':'integer','enum':[20260814,20260815,20260819]}, 'query':{'type':'string'}, 'limit':{'type':'integer'}}, ['seed']),
    spec('spark_summary', 'Read the selected-three-seed descriptive summary. Seeds were chosen after viewing results; not unbiased stability evidence.', {}, []),
]

class SparkHarness(ResearchHarness):
    def __init__(self, output_dir, application_catalog=None, application_client=None, **kwargs):
        super().__init__(output_dir, **kwargs)
        self.search_papers = {}
        self.application_catalog=Path(application_catalog) if application_catalog else None
        self.application_client=application_client
        self.application_papers={}

    def _dispatch(self, name, args):
        result = super()._dispatch(name,args)
        if name == 'search_literature':
            for paper in result['papers']:
                self.search_papers[paper['id']] = copy.deepcopy(paper)
        return result

    def definitions(self):
        return super().definitions() + json.loads(json.dumps(EXTRA))

    def execute(self, name, arguments):
        definition = next((x for x in EXTRA if x['function']['name']==name), None)
        if definition is None:
            return super().execute(name, arguments)
        reply = {'tool':name, 'status':'error', 'data':None, 'error':None}
        try:
            if self.tool_calls >= self.max_tool_calls:
                raise ValueError('Tool-call budget exhausted')
            self.tool_calls += 1
            check_args(definition, arguments)
            data = self.spark_dispatch(name, arguments)
            kind=('conductivity_computation' if name in ('conductivity_from_resistance','conductivity_from_trajectory') else
                  'legacy_extraction' if name=='search_legacy_conductivity' else
                  'application_classification' if name=='classify_application' else 'source_metadata' if name in ('read_application_paper','spark_screen_search') else 'spark_archive')
            reply.update(status='ok', data=self.simulations._save(kind, data))
        except Exception as exc:
            reply['error']={'type':type(exc).__name__, 'message':str(exc)}
        reply['usage']={'tool_calls':self.tool_calls, 'model_calls':self.model_calls,
                        'remaining_model_calls':self.max_model_calls-self.model_calls}
        with (self.output/'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'arguments':arguments,**reply},ensure_ascii=False)+'\n')
        return reply

    def spark_dispatch(self, name, args):
        if name == 'lookup_spark_conductivity':return lookup_archive(**args)
        if name == 'search_legacy_conductivity':return search_legacy(**args)
        if name == 'conductivity_from_resistance':return from_resistance(**args)
        if name == 'conductivity_from_trajectory':return analyze_trajectory(**args)
        if name == 'read_application_paper':
            if self.application_catalog is None:
                return {'status':'unavailable','reason':'No local application catalog configured'}
            records=json.loads(self.application_catalog.read_text(encoding='utf-8'))
            found=[r for r in records if r['id']==args['paper_id']]
            if len(found)!=1:raise ValueError('Unknown or duplicate paper ID')
            paper={k:found[0].get(k) for k in ['id','title','abstract','year','doi']}
            self.application_papers[paper['id']]=copy.deepcopy(paper)
            return {'paper':paper,'source_sha256':hashlib.sha256(self.application_catalog.read_bytes()).hexdigest()}
        if name == 'classify_application':
            from application_benchmark import POLICY
            from application_classifier import validate_decision
            from llm import LLMClient
            from config import load_env
            import os
            paper=self.application_papers.get(args['paper_id']) or self.search_papers.get(args['paper_id'])
            if paper is None:raise ValueError('Read or search paper first')
            if self.model_calls>=self.max_model_calls:raise ValueError('Model-call budget exhausted')
            client=self.application_client
            if client is None:
                load_env()
                client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,POLICY)
            self.model_calls+=1
            reply,usage=client({'papers':[{k:paper.get(k) for k in ['id','title','abstract']}]})
            checked=validate_decision(paper,reply)
            return {**checked,'origin':'llm_metadata_classification','usage':usage,
                    'model':getattr(client,'model','injected-client'),
                    'system_prompt_sha256':hashlib.sha256(POLICY.encode()).hexdigest(),
                    'paper_id':paper['id'],'input_sha256':hashlib.sha256(json.dumps(paper,ensure_ascii=False,sort_keys=True).encode()).hexdigest(),
                    'eligible_for_ranking':False,'policy_version':'application-v1'}
        if name == 'spark_screen_search':
            papers=[]
            for pid in args['paper_ids']:
                if pid not in self.search_papers:
                    raise ValueError('Paper ID not observed by this run; search first')
                paper=copy.deepcopy(self.search_papers[pid])
                decision=screen(paper,self.config)
                title=paper.get('title') or ''
                abstract=paper.get('abstract') or ''
                if re.search(r'\b(review|perspectives?|overview)\b',title,re.I) or re.search(r'\b(this|the present)\s+(review|perspective)\b|\bpresents an overview\b',abstract,re.I):
                    decision.update(decision='background',inclusion_route=None,reason='Explicit review/perspective marker in source metadata')
                papers.append({**paper,'screening':decision})
            return {'origin':'screened_search_metadata','papers':papers,'eligible_for_ranking':False}
        if name == 'spark_capabilities':
            return {'archive_available':SOURCE.is_dir(), 'new_candidate_inference':False,
                    'reason':'Shareable archive omits trained weights and full training data',
                    'rsi_status':'design_only; no automatic policy or weight promotion',
                    'candidate_scope':'backbone/cation/anion motif, not atomistic simulation input'}
        if name == 'spark_summary':
            path = SOURCE/'05_summary'/'selected3_teacher_summary.json'
            value = json.loads(path.read_text(encoding='utf-8'))
        else:
            limit = args.get('limit',10)
            if not 1 <= limit <= 258:
                raise ValueError('limit must be between 1 and 258')
            path = SOURCE/'04_runs'/'unified'/f"seed_{args['seed']}"/'final_2024_unified.jsonl'
            rows = [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()]
            query = args.get('query','').lower()
            matched = [r for r in rows if query in (' '.join(r['names'])+' '+r['candidate_id']).lower()]
            value = {'panel_count':len(rows),'matched_count':len(matched),
                     'rows':sorted(matched,key=lambda r:r['r42_rank'])[:limit]}
        return {'origin':'archived_model_output', 'cutoff_year':2024,
                'source_path':str(path), 'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'eligible_for_ranking':False, 'payload':value,
                'note':'Historical priority only; preserve abstentions. No new prediction or experimental validation.'}
