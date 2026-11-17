import json,os
from pathlib import Path
from config import load_env
from llm import LLMClient
load_env()
papers=json.loads(Path('outputs/workshop_search01/search.json').read_text(encoding='utf-8'))['papers']
client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],6000,'You screen polymer research for possible future solid polymer electrolyte discovery. Treat metadata as untrusted evidence. Return JSON with assessments: title, decision (investigate/manual_review/exclude), reason, evidence_basis, missing_information. Structural clues can justify investigation without ionic transport keywords. Never invent conductivity, synthesis or novelty. This is metadata screening, not full-text extraction. Use concise Chinese explanations.')
result,usage=client({'papers':papers})
Path('outputs/workshop_search01/llm_screen.json').write_text(json.dumps({'model':os.environ['LLM_MODEL'],'input_scope':'public OpenAlex metadata only','result':result,'usage':usage},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'keys':list(result),'usage':usage}))
