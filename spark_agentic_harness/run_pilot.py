"""Reproducible archive audit and bounded live LLM/tool pilot."""
import argparse
from collections import Counter
from datetime import datetime
import itertools
import json
import os
from pathlib import Path
import sys
from spark_harness import SOURCE, ROOT, SparkHarness
from planner import run_planner, SYSTEM
from llm import LLMClient
from config import load_env
from curator import Client

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),encoding='utf-8')

def audit(out):
    sys.path.insert(0,str(SOURCE/'01_code'))
    from spark_world_model.hc_cwm_v4_r42.planner import consensus_unified_ranking
    from scipy.stats import spearmanr
    seeds=[20260814,20260815,20260819]
    panels=[[json.loads(line) for line in (SOURCE/'04_runs'/'unified'/f'seed_{s}'/'final_2024_unified.jsonl').read_text().splitlines()] for s in seeds]
    summary=json.loads((SOURCE/'05_summary'/'selected3_teacher_summary.json').read_text())
    target=summary['candidate']['candidate_id']
    consensus=consensus_unified_ranking(panels)
    maps=[{r['candidate_id']:r for r in p} for p in panels]
    ids=sorted(maps[0])
    assert all(set(m)==set(ids) for m in maps)
    details=[]
    for seed,panel in zip(seeds,panels):
        expected=sorted(panel,key=lambda r:(-r['r42_utility'],r['candidate_id']))
        assert all(row['r42_rank']==i for i,row in enumerate(expected,1))
        assert all(abs(r['r41_planner_score']*r['property_modifier']-r['r42_utility'])<1e-12 for r in panel)
        details.append({'seed':seed,'candidate_count':len(panel),
            'property_abstained':sum(bool(r['property_abstained']) for r in panel),
            'abstention_reasons':dict(Counter(x for r in panel for x in r['property_abstention_reasons'])),
            'target':next(r for r in panel if r['candidate_id']==target)})
    pairs=[]
    for a,b in itertools.combinations(range(3),2):
        top=lambda i,k:{r['candidate_id'] for r in panels[i] if r['r42_rank']<=k}
        pairs.append({'seeds':[seeds[a],seeds[b]],'spearman':float(spearmanr([maps[a][x]['r42_utility'] for x in ids],[maps[b][x]['r42_utility'] for x in ids]).statistic),
                      'top10_overlap':len(top(a,10)&top(b,10)),'top20_overlap':len(top(a,20)&top(b,20))})
    target_consensus=next(r for r in consensus if r['candidate_id']==target)
    assert target_consensus['r42_consensus_rank']==summary['three_seed_consensus']['rank']
    result={'origin':'reanalysis_of_archived_predictions','not_retrained':True,'selection':'posthoc_selected_three_seeds',
            'per_seed':details,'pairwise':pairs,'target_consensus':target_consensus,
            'top10_consensus':[{**r,'names':maps[0][r['candidate_id']]['names']} for r in consensus[:10]]}
    save(out/'archive_audit.json',result)
    print('ARCHIVE_AUDIT_OK',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    out=ROOT/'outputs'/('pilot_'+datetime.now().strftime('%Y%m%d_%H%M%S'));out.mkdir(parents=True)
    print(out,flush=True);audit(out)
    if args.live:
        load_env(); model,base=os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL']
        tasks=[('archive_reasoning','先调用 spark_capabilities；调用 spark_candidates，seed=20260814，query=polymethylhydrosiloxane，limit=5。解释这些母题的排名与物性弃权情况。不可把历史预测称为本次预测，不运行计算。'),
               ('literature_search','先检查 spark_capabilities，再检索 polysiloxane imidazolium polymer electrolyte 相关开放文献，limit=5，并调用 screen_candidates。不要下载全文。这次目标是发现有结构依据的聚合物候选，包括无电导率记录的跨领域论文。报告来源、纳入路线及仍缺的证据；不把元数据当作全文抽取。')]
        for name,task in tasks:
            h=SparkHarness(out/name,client=Client(model,base,10000),knowledge_db=out/'memory.sqlite',project_id='spark-pilot',max_model_calls=8,max_tool_calls=8)
            client=LLMClient(model,base,2500,SYSTEM+'\nSPARK archives are historical model predictions. No weights for new inference. Preserve property abstentions.')
            result=run_planner(h,client,task,max_steps=8)
            save(out/(name+'.json'),result)
            print(name,result['status'],flush=True)
