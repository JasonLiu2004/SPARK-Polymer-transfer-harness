"""Same policy cases/prompt, larger completion budget; preserve failed baseline."""
import json
import os
from datetime import datetime
from build_review_benchmark import OUT
from config import load_env
from llm import LLMClient

if __name__=='__main__':
    load_env()
    parent=OUT/'eval_111504'
    out=OUT/('abstention_8192_'+datetime.now().strftime('%H%M%S'));out.mkdir()
    print(out,flush=True)
    prompt='Return JSON {"decisions":[{"id":...,"action":...}]}. For each case select one action: use_for_material_ranking, retain_and_seek_evidence, discard_as_zero, claim_dry_SPE, quarantine_for_review, query_archived_seed, unavailable_without_weights. Follow evidence reliability and application conditions. Never equate missing conductivity to zero. Archive lookup does not require weights.'
    client=LLMClient(os.environ['LLM_MODEL'],os.environ['LLM_BASE_URL'],8192,prompt)
    for i in range(3):
        baseline=json.loads((parent/f'abstention_{i}.json').read_text(encoding='utf-8'))
        try:reply,usage=client({'cases':baseline['request']})
        except Exception as exc:reply,usage={'error_type':type(exc).__name__},{}
        checks=[]
        for item in baseline['checks']:
            matches=[d for d in reply.get('decisions',[]) if d.get('id')==item['id']]
            checks.append({**item,'pass':len(matches)==1 and matches[0].get('action')==item['expected']})
        (out/f'repeat_{i}.json').write_text(json.dumps({'system_prompt':prompt,'max_tokens':8192,'request':baseline['request'],'reply':reply,'usage':usage,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
        print(i, 'valid',isinstance(reply.get('decisions'),list),'pass',sum(c['pass'] for c in checks),flush=True)
