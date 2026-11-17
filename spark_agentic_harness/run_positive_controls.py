import concurrent.futures,json
import run_extended as runner
from config import load_env
from spark_harness import ROOT

if __name__=='__main__':
    load_env()
    runner.OUT=ROOT/'outputs/extended_20261117/positive_controls'
    runner.OUT.mkdir(exist_ok=True,parents=True)
    cases=json.loads((ROOT/'outputs/batch10_20261117/cases.json').read_text(encoding='utf-8'))[:5]
    old={p['id']:p for p in json.loads((ROOT/'outputs/batch10_20261117/catalog.json').read_text(encoding='utf-8'))}
    papers=[old[c['paper_id']] for c in cases]
    (runner.OUT/'catalog.json').write_text(json.dumps(papers,ensure_ascii=False,indent=2),encoding='utf-8')
    (runner.OUT/'reference.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf-8')
    (runner.OUT/'manifest.json').write_text(json.dumps({'n':5,'purpose':'positive controls for automatic extraction replacing earlier curated inputs','new_papers':0,'paired_direct_calls':5,'source_case_ids':[c['case_id'] for c in cases]},ensure_ascii=False,indent=2),encoding='utf-8')
    jobs=[(m,i,p) for i,p in enumerate(papers,1) for m in ['harness','direct']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(runner.run_job,jobs))
    (runner.OUT/'run_summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Positive controls completed',len(results),flush=True)
