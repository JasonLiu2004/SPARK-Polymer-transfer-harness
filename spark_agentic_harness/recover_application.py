"""At most four two-paper recovery calls for the failed eight-paper batch.
Original predictions/scores remain immutable; produces a separate comparison.
"""
import argparse
import json
import os
from pathlib import Path
from application_benchmark import POLICY,dump,metrics
from application_classifier import validate_decision
from config import load_env
from llm import LLMClient

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('run',type=Path);args=parser.parse_args();out=args.run
    initial=json.loads((out/'comparison.json').read_text(encoding='utf-8'))
    unresolved=[x['source'] for x in initial['results'] if not x['llm']]
    if len(unresolved)>8:raise ValueError('Recovery capped at eight papers')
    load_env();client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,POLICY)
    recovered={};usages=[]
    for offset in range(0,len(unresolved),2):
        state={'papers':[{k:r[k] for k in ['id','title','abstract']} for r in unresolved[offset:offset+2]]}
        path=out/f'recovery_{offset//2}.json'
        if path.exists():payload=json.loads(path.read_text(encoding='utf-8'))
        else:
            try:reply,usage=client(state)
            except Exception as e:reply,usage={'error_type':type(e).__name__},{}
            payload={'request':state,'reply':reply,'usage':usage};dump(path,payload)
        usages.append(payload.get('usage',{}));rows=payload['reply'].get('papers',[])
        if isinstance(rows,list):
            for paper in state['papers']:
                matches=[r for r in rows if isinstance(r,dict) and r.get('id')==paper['id']]
                if len(matches)==1:recovered[paper['id']]=matches[0]
        print(offset//2,'recovered so far',len(recovered),flush=True)
    checked=[]
    for item in initial['results']:
        source=item['source'];decision=recovered.get(source['id']) or item['llm']
        validation=validate_decision(source,{'papers':[decision]} if decision else {})
        checked.append({'source':source,'validation':validation})
    eligible=[r for r in checked if r['validation']['status']=='classified_unreviewed']
    result={'pilot_n':len(checked),'accepted_n':len(eligible),'coverage':len(eligible)/len(checked),
            'additional_calls':len(usages),'additional_total_tokens':sum(u.get('total_tokens',0) for u in usages),
            'llm_silver_agreement_on_accepted':metrics([r['source']['silver_label'] for r in eligible],[int(r['validation']['decision']['spe_label']=='spe') for r in eligible]) if eligible else None,
            'baseline_on_same_accepted':metrics([r['source']['silver_label'] for r in eligible],[r['source']['baseline_label'] for r in eligible]) if eligible else None,
            'results':checked,'note':'Adaptive recovery costs extra calls. Original 4-batch evaluation unchanged; accepted-only accuracy excludes abstentions and invalid evidence.'}
    dump(out/'recovered_comparison.json',result)
    print({k:v for k,v in result.items() if k!='results'},flush=True)
