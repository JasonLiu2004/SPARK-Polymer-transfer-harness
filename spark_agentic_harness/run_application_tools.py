"""One real classify_application call through shared budgets and persistent memory."""
import argparse
import json
from pathlib import Path
from datetime import datetime
from spark_harness import SparkHarness,ROOT

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',type=Path,required=True);args=parser.parse_args()
    records=json.loads(args.catalog.read_text(encoding='utf-8'));pid=records[0]['id']
    out=ROOT/'outputs'/('application_tool_'+datetime.now().strftime('%Y%m%d_%H%M%S'))
    h=SparkHarness(out,application_catalog=args.catalog,project_id='application-pilot',max_model_calls=1)
    read=h.execute('read_application_paper',{'paper_id':pid})
    result=h.execute('classify_application',{'paper_id':pid})
    memory=h.execute('get_simulation_record',{'record_id':result['data']['record_id']}) if result['data'] else None
    (out/'result.json').write_text(json.dumps({'read':read,'classify':result,'memory':memory},ensure_ascii=False,indent=2),encoding='utf-8')
    print(out,flush=True);print(result['status'],result.get('data',{}).get('status'),flush=True)
