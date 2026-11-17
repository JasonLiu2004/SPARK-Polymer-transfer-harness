"""Check copied inputs and code inventory without exposing credentials."""
from pathlib import Path
import json,hashlib,sys,re
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 out=ROOT/'verification';out.mkdir(exist_ok=True)
 inventory=json.loads((ROOT/'spark_agentic_harness/outputs/local_corpus_inventory.json').read_text(encoding='utf-8'))
 checked=[]
 for row in inventory['files']:
  for rel in row['paths']:
   p=ROOT/rel
   checked.append({'path':rel,'exists':p.is_file(),'sha256_matches':p.is_file() and sha(p)==row['sha256']})
 code=[]
 for p in ROOT.rglob('*'):
  if p.is_file() and p.suffix in {'.py','.mjs','.js','.ps1','.ipynb'} and not any(s in p.parts for s in ['__pycache__','.deps','.runtime']):
   code.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':sha(p)})
 log=(ROOT/'verification-tests.txt').read_text(encoding='utf-8-sig',errors='replace')
 counts=[int(x) for x in re.findall(r'Ran (\d+) tests?',log)]
 tests_ok=counts==[38,14] and len(re.findall(r'^OK\s*$',log,re.M))==2 and 'FAILED (' not in log
 outputs=ROOT/'spark_agentic_harness/outputs'
 smoke_path=sorted(outputs.glob('20*/result.json'))[-1]
 smoke=json.loads(smoke_path.read_text(encoding='utf-8'))
 completion_path=sorted(outputs.glob('conductivity_completion_*/results.json'))[-1]
 completion=json.loads(completion_path.read_text(encoding='utf-8'))
 hpg=json.loads((ROOT/'spark_agentic_harness/external_conductivity/results/hpg_summary.json').read_text(encoding='utf-8'))
 runs={'spark_archive':all(r['status']=='ok' for r in smoke),'completion':all(r['status']=='ok' for r in completion.values()),'hpg_validation_reproduced':hpg['n']==78 and abs(hpg['MAE_log10_S_cm']-0.23493558084823418)<1e-7}
 result={'pdf_records':len(checked),'all_pdfs_verified':all(r['exists'] and r['sha256_matches'] for r in checked),'code_files':len(code),'root_env_exists':(ROOT/'.env').is_file(),'root_env_example_exists':(ROOT/'.env.example').is_file(),'tests':{'suite_counts':counts,'status':'passed' if tests_ok else 'failed','log':'verification-tests.txt'},'offline_runs':runs,'code_manifest':code,'input_checks':checked}
 (out/'bundle_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:v for k,v in result.items() if k not in ['code_manifest','input_checks']},ensure_ascii=False))
 return 0 if result['all_pdfs_verified'] and tests_ok and all(runs.values()) else 1
if __name__=='__main__':sys.exit(main())
