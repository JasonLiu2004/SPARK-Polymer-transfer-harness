from pathlib import Path
import json,os
from online import download_pdf
from curator import Client
from config import load_env
from harness import ResearchHarness
load_env()
out=Path('outputs/workshop_llm01');out.mkdir(parents=True,exist_ok=True)
paper=json.loads(Path('outputs/workshop_search01/search.json').read_text(encoding='utf-8'))['papers'][0]
path, provenance=download_pdf(paper['pdf_urls'][0],out/'downloads')
h=ResearchHarness(out/'run',client=Client(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],6000),max_model_calls=3)
a=h.execute('open_corpus',{'paths':[str(path)]})
result=h.execute('extract_records',{'corpus_id':a['data']['corpus_id'],'max_calls':3})
(out/'summary.json').write_text(json.dumps({'origin':'online_manual_review','paper':paper,'provenance':provenance,'response':result},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'status':result['status'],'error':result['error'],'usage':result['usage']}))
