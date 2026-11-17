import argparse,json
from pathlib import Path
from harness import TemporalHarness,definitions
def main():
 p=argparse.ArgumentParser(description='Two-window polymer transfer discovery')
 p.add_argument('--start',type=int,default=2015);p.add_argument('--years',type=int,default=5)
 p.add_argument('--out',required=True);p.add_argument('--catalog');p.add_argument('--discover',action='append',default=[])
 p.add_argument('--validate',action='append',default=[]);p.add_argument('--pages',type=int,default=1)
 p.add_argument('--tools',action='store_true');a=p.parse_args()
 if a.tools:print(json.dumps(definitions(),indent=2));return
 h=TemporalHarness(a.out,a.start,a.years)
 records=json.loads(Path(a.catalog).read_text(encoding='utf-8')) if a.catalog else []
 # Future records never enter discovery prompts or scoring.
 sources=[r for r in records if a.start<=r['year']<a.start+a.years]
 for query in a.discover:sources+=h.execute('search_window',{'query':query,'phase':'discovery','max_pages':a.pages})['papers']
 for paper in sources:
  if not h.state['frozen']:h.execute('extract_source',{'paper':paper})
 h.execute('freeze_ranking',{})
 future=[r for r in records if a.start+a.years<=r['year']<a.start+2*a.years]
 for query in a.validate:future+=h.execute('search_window',{'query':query,'phase':'validation','max_pages':a.pages})['papers']
 for paper in future:h.execute('validate_later',{'paper':paper})
 result=h.execute('report',{});print(json.dumps({'ranked':len(result['rows']),'report':str(Path(a.out)/'report.json')},ensure_ascii=False))
if __name__=='__main__':main()
