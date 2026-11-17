import argparse
import json
import os
from pathlib import Path
from datetime import datetime
from spark_harness import SparkHarness, ROOT
from planner import run_planner, SYSTEM
from config import load_env
from llm import LLMClient
from curator import Client

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--task', help='Enable LLM orchestration; omitted means offline archive smoke test')
    parser.add_argument('--application-catalog',type=Path,help='Frozen local title/abstract JSON catalog')
    args=parser.parse_args()
    out=ROOT/'outputs'/datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    options={'knowledge_db':ROOT/'outputs'/'memory.sqlite','project_id':'spark-discovery','application_catalog':args.application_catalog}
    if args.task:
        load_env()
        model,base=os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL']
        h=SparkHarness(out,client=Client(model,base,10000),**options)
        client=LLMClient(model,base,4096,SYSTEM+'\nUse spark_capabilities first. Archived SPARK outputs are not new predictions. Never invent missing model weights. Motifs need explicit chemical structures before MD.')
        result=run_planner(h,client,args.task,max_steps=12)
    else:
        h=SparkHarness(out,**options)
        result=[h.execute('spark_capabilities',{}),h.execute('spark_summary',{}),
                h.execute('spark_candidates',{'seed':20260814,'query':'polymethylhydrosiloxane','limit':10})]
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(out)
