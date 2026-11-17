"""Unified entry point. All project paths resolve inside this folder."""
import argparse,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SCRIPTS={
 'temporal':'temporal_harness/run.py',
 'smoke':'spark_agentic_harness/run.py',
 'completion':'spark_agentic_harness/run_completion_demo.py',
 'plan':'spark_agentic_harness/run.py',
 'batch10':'spark_agentic_harness/run_batch10.py',
 'case':'spark_agentic_harness/run_case_study.py',
 'hpg':'spark_agentic_harness/external_conductivity/test_public_hpg.py',
 'scan':'spark_agentic_harness/external_conductivity/test_public_scan.py',
 'baseline':'spark_agentic_harness/external_conductivity/test_structure_baseline.py',
}
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('command',choices=['test',*SCRIPTS])
 args,extra=p.parse_known_args()
 if args.command=='test':
  for folder in ['spe_agentic_harness','spark_agentic_harness']:
   result=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(ROOT/folder),'-p','test_*.py',*extra],cwd=ROOT)
   if result.returncode:return result.returncode
  return 0
 if args.command=='plan' and '--task' not in extra:p.error('plan requires --task "研究问题"')
 return subprocess.run([sys.executable,str(ROOT/SCRIPTS[args.command]),*extra],cwd=ROOT).returncode
if __name__=='__main__':raise SystemExit(main())
