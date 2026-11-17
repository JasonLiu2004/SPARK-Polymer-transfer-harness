from pathlib import Path
import os,json
from config import load_env
from curator import Corpus,Client,run
load_env()
pdf=next(Path('outputs/target_download01/downloads').glob('*.pdf'))
client=Client(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],10000)
client.system_prompt += '\nFor this computational paper add a data_origin field to every record using the same value/unit/evidence structure. Distinguish MD simulation, machine-learning prediction, literature-reported experiment and experiment performed in this paper. Never relabel simulated conductivity as measured conductivity. Keep data_origin unknown if unsupported. Extract only identifiable material records, not hypothetical combinations.'
corpus=Corpus([pdf])
corpus.sources[0]['url']='https://arxiv.org/pdf/2101.05339'
out=Path('outputs/llm_extraction_experiment01')
result=run(corpus,client,out,max_calls=3)
(out/'experiment_config.json').write_text(json.dumps({'model':client.model,'base_url':client.base_url,'max_calls':3,'max_output_tokens':10000,'system_prompt':client.system_prompt,'source_url':'https://arxiv.org/pdf/2101.05339'},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':result['status'],'calls':result['calls'],'records':len(result['records']),'issues':len(result['issues']),'usage':result['usage']}))
