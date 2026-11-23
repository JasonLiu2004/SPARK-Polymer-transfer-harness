"""Independent, DOI-keyed public bibliographic records, never pre-existing names, graphs or labels."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from html import unescape
from pathlib import Path
import argparse
import json
import re
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from common import DATA, WORK, YEARS, file_hash, fingerprint, seal, verified

JOURNAL="https://api.crossref.org/journals/0032-3896/works"
PMC="https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TOPIC=('(TITLE:"polymer membrane" OR TITLE:"polymeric membrane" OR TITLE:"polymer scaffold" OR '
       'TITLE:"polymeric scaffold" OR TITLE:"polymer coating" OR TITLE:"polymeric coating") AND '
       '(TITLE_ABS:"gas separation" OR TITLE_ABS:"water purification" OR TITLE_ABS:"tissue engineering" OR TITLE_ABS:"corrosion protection")')
INTERVALS=[(1950,2004),(2005,2009),(2010,2014),(2015,2019),(2020,2024)]


def plain(v):
    return " ".join(unescape(re.sub(r"<[^>]*>"," ",v or "")).split())


def get(params):
    req=Request(PMC+"?"+urlencode(params),headers={"User-Agent":"Polymer-Adoption-Harness academic research","Accept":"application/json"})
    for i in range(4):
        try:
            with urlopen(req,timeout=55) as r:
                return json.load(r)
        except OSError:
            if i==3: raise
            time.sleep(2**i)


def get_topic(interval):
    lo,hi=interval
    path=DATA/"cross_domain"/f"{lo}_{hi}.json"
    if path.exists():return verified(path)
    query=TOPIC+f" AND FIRST_PDATE:[{lo}-01-01 TO {hi}-12-31]"
    params={"query":query,"resultType":"core","format":"json","pageSize":200,"cursorMark":"*"}
    seen=set();papers={}
    while True:
        r=get(params);items=r["resultList"]["result"]
        for item in items:
            seen.add((item["source"],item["id"]))
            doi=(item.get("doi") or "").casefold()
            when=item.get("firstPublicationDate","")
            if not doi or not when or not item.get("title"):continue
            year=date.fromisoformat(when).year
            if not lo<=year<=hi:raise ValueError("Cross-domain DOI outside requested interval")
            paper={"doi":doi,"year":year,"title":plain(item["title"]),"abstract":plain(item.get("abstractText")),
                   "types":item.get("pubTypeList",{}).get("pubType",[]),"sources":["Europe PMC cross-domain"],"date":when}
            if len(paper["abstract"]) >= len(papers.get(doi,{}).get("abstract","")):
                papers[doi]=paper
        cursor=r.get("nextCursorMark")
        if len(seen)>=r["hitCount"] or not items or cursor==params["cursorMark"] or not cursor:break
        params["cursorMark"]=cursor
    if len(seen)!=r["hitCount"]:raise ValueError("Incomplete pagination for cross-domain search")
    return seal(path,{"source":PMC,"query":query,"hits":len(seen),"papers":papers})


def raw_paths(stream):
    # Explicit allowlist. Only the raw exports with their documented query/URL can enter.
    old=WORK/"SPARK_Full_Transfer_20261120"/"runs"
    v6=WORK/"SPARK_Evidence_Transfer_Harness_v6"/"data"
    if stream=="broad":
        return [v6/"broad"/f"{y}.json" for y in range(2000,2010)]+[
            old/"journal_extension/crossref"/f"{y}.json" for y in range(2010,2025)]+[
            DATA/"cross_domain"/f"{lo}_{hi}.json" for lo,hi in INTERVALS]
    folder={"spe":v6/"target","independent":old/"holdout/target"}[stream]
    return [folder/f"{lo}_{hi}.json" for lo,hi in INTERVALS]


def papers(stream,through):
    docs={};lineage=[]
    for path in raw_paths(stream):
        if int(path.stem.split("_")[-1])>through:continue
        src=verified(path)
        if src.get("source") not in (JOURNAL,PMC) or not (src.get("query") or src.get("filter")):
            raise ValueError("Only independent search API exports can be imported")
        lineage.append({"file":str(path.relative_to(WORK)),"sha":src["sha256"],"search":src.get("query") or src["filter"]})
        for doi,p in src["papers"].items():
            doi=doi.casefold()
            if p["doi"].casefold()!=doi or not p.get("title") or p["year"]>through:continue
            # An earlier publication cannot acquire the later version's abstract.
            new={k:p.get(k) for k in ("doi","title","year","date","abstract","sources","types")}
            old=docs.get(doi)
            if old is None or new["year"]<old["year"] or (new["year"]==old["year"] and len(new["abstract"] or "")>len(old["abstract"] or "")):
                docs[doi]=new
    return docs,lineage


if __name__=="__main__":
    with ThreadPoolExecutor(max_workers=3) as pool:
        for v in pool.map(get_topic,INTERVALS):
            print(v["query"].split("FIRST_PDATE:")[-1],v["hits"],len(v["papers"]),flush=True)
