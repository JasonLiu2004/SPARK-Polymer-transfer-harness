"""Live OpenAlex work counts; never confuse keyword hits with eligible candidates."""
from datetime import datetime,timezone
import argparse
import json
import os
from urllib.parse import urlencode
from spark_harness import ROOT
from config import load_env
from online import fetch

QUERIES={
 'pilot_narrow':'polysiloxane AND imidazolium AND polymer AND electrolyte',
 'electrolyte_core':'polymer AND electrolyte',
 'structural_transfer':'polymer AND (coordination OR dielectric OR "glass transition" OR "free volume")',
 'union':'polymer AND (electrolyte OR coordination OR dielectric OR "glass transition" OR "free volume")',
}
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--scope',choices=['all','title_abstract'],default='title_abstract')
    args=parser.parse_args()
    load_env();out=ROOT/'outputs'/('search_counts_'+datetime.now().strftime('%Y%m%d_%H%M%S'));out.mkdir()
    print(out,flush=True);results=[]
    headers={'Authorization':'Bearer '+os.environ['OPENALEX_API_KEY']} if os.environ.get('OPENALEX_API_KEY') else {}
    jobs=[(name,q,oa,None) for name,q in QUERIES.items() for oa in (False,True)]
    jobs += [('union_2004_2024',QUERIES['union'],False,'2004-01-01')]
    for name,q,oa,start in jobs:
        filters=['to_publication_date:2024-12-31','type:article|review']
        if oa:filters.append('open_access.is_oa:true')
        if start:filters.append('from_publication_date:'+start)
        search_key='search.title_and_abstract' if args.scope=='title_abstract' else 'search'
        params={search_key:q,'filter':','.join(filters),'per-page':1,'select':'id,display_name,publication_year,doi'}
        url='https://api.openalex.org/works?'+urlencode(params)
        row={'name':name,'query':q,'scope':args.scope,'open_access_only':oa,'from_date':start,'to_date':'2024-12-31','types':['article','review'],'url':url,'retrieved_at':datetime.now(timezone.utc).isoformat()}
        try:
            raw,_=fetch(url,headers=headers);data=json.loads(raw)
            row.update(count=data['meta']['count'],meta=data['meta'],example=data.get('results',[]))
        except Exception as e:row['error_type']=type(e).__name__
        results.append(row);(out/'counts.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(name,'OA' if oa else 'ALL',row.get('count',row.get('error_type')),flush=True)
