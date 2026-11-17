"""Frozen-data shadow evaluation of one scope-definition change; no promotion."""
import json,os,time,concurrent.futures,hashlib
from spark_harness import ROOT
from transport_extraction import PROMPT,validate,assess
from config import load_env
from llm import LLMClient
OUT=ROOT/'outputs/extended_20261117/policy_trial'
DELTA='''
Scope clarification v2: material_role=polymer_electrolyte includes polymer/ceramic composite electrolytes containing an ion-conducting polymer phase, even when ceramic dominates mass or transport. Preserve that composite qualification in sample and issues; never call its measured conductivity intrinsic polymer conductivity. Use ceramic_filler only for a value measured on the isolated ceramic/filler, not for the complete polymer/ceramic composite. All temperature, energy-type, sample-association and quote rules remain unchanged.'''
def run(item):
    key,paper=item;path=OUT/(key+'.json')
    if path.exists():return
    start=time.time()
    client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,PROMPT+DELTA)
    try:
        raw,usage=client({'paper':paper})
        result={'key':key,'paper_id':paper['id'],'model':client.model,'extraction':raw,'usage':usage,
          'evidence_issues':validate(paper,raw),'assessment':assess(paper,raw),'elapsed_seconds':round(time.time()-start,2)}
    except Exception as e:result={'key':key,'paper_id':paper['id'],'error_type':type(e).__name__}
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(key,result.get('assessment',{}).get('status',result.get('error_type')),flush=True)
if __name__=='__main__':
    load_env();OUT.mkdir(parents=True,exist_ok=True)
    base=ROOT/'outputs/extended_20261117'
    papers=json.loads((base/'catalog.json').read_text(encoding='utf-8'))
    positive=json.loads((base/'positive_controls/catalog.json').read_text(encoding='utf-8'))
    jobs=[(f'boundary_{i:02}',p) for i,p in enumerate(papers,1)]+[(f'positive_{i:02}',p) for i,p in enumerate(positive,1)]
    (OUT/'manifest.json').write_text(json.dumps({'n':25,'delta':DELTA,'base_prompt_sha256':hashlib.sha256(PROMPT.encode()).hexdigest(),
      'new_prompt_sha256':hashlib.sha256((PROMPT+DELTA).encode()).hexdigest(),'ids':[p['id'] for _,p in jobs],
      'proposer':'assistant after observing C05 failure','evaluation':'development-set shadow test; not independent held-out validation',
      'promotion':'not promoted; no modification to original extraction prompt or original results'},ensure_ascii=False,indent=2),encoding='utf-8')
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(run,jobs))
    print('Policy trial completed',flush=True)
