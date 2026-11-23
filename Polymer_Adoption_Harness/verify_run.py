"""Offline audit of source coverage, time order, real model receipts and mandatory admission."""
from datetime import datetime
from common import DATA,ROOT,RUN,YEARS,file_hash,fingerprint,read_json,verified,write_json
from corpus import papers
from graph import build
from physics import CHECKPOINT_SHA,GRID


def check(condition,message):
    if not condition:raise ValueError(message)


def moment(record):
    return datetime.fromisoformat(record["sealed_at"])


def audit(home=ROOT/"runs"/"adoption"):
    grid=verified(DATA/"physics/grid.json")
    protocol=verified(home/"protocol.json");threshold=protocol["threshold_S_cm"]
    source=home/"registered_source" if (home/"registered_source").is_dir() else ROOT
    for name,digest in protocol["code"].items():
        check(file_hash(source/name)==digest,"Registered source checksum differs: "+name)
    covered={};requests=set();windows=[];last_feedback=None;past_graph=None
    pins={};ledger={};references=set()
    for path in (home/"decisions").rglob("*.json"):
        d=verified(path);pins[d["sha256"]]=d
    for stream in ("broad","spe","independent"):
        batches=list((DATA/"intervals"/stream).glob("*.json"));ids=set()
        for path in batches:
            d=verified(path);requests.update(("extract",key) for key in d["receipts"])
            check(not ids.intersection(d["records"]),"Duplicate interval coverage")
            ids.update(d["records"])
        check(ids==set(papers(stream,2024)[0]),stream+" missing raw publication")
        covered[stream]=ids
    for y in YEARS:
        if last_feedback:
            prior=verified(home/str(y)/"forecast.json")
            check(prior["policy"]==last_feedback["updated_policy"] and moment(last_feedback)<=moment(prior),"Out-of-order learning")
        f=verified(home/str(y)/"forecast.json");g=verified(home/str(y)/"graph.json")
        check(f["protocol"]==protocol["sha256"] and f["graph"]==g["sha256"] and g["previous"]==past_graph,"Broken forecast/graph chain")
        past_graph=g["sha256"]
        records=verified(next((DATA/"intervals/broad").glob(f"*_{y}.json")))["records"]
        ledger.update(records);_,panel=build(ledger,y);rows=f["rankings"]
        check(panel.keys()==rows.keys(),"Source-backed material missing from full forecast")
        counts={"cutoff":y,"qualified":0,"qualified_recipes":0,"qualified_admitted":0,"hpg_only":0}
        for n,r in rows.items():
            first=min(panel[n]["sources"],key=lambda e:(e["year"],e["doi"]))
            check(first["year"]<=y and all(e["year"]<=y for e in panel[n]["sources"]),"Future source in material evidence")
            designs=grid["designs"].get(n,[])
            if designs:
                check({(d["salt_wt_pct"],d["temperature_C"]) for d in designs}=={(p,t) for p in GRID[0] for t in GRID[1]},"Incomplete recipe grid")
            good={d["recipe"] for d in designs if d["status"]=="predicted" and d["sigma_S_cm"]>=threshold}
            qualifying=r["qualifying_recipes"]
            check(good=={d["recipe"] for d in qualifying},"Lost qualifying formulation")
            check(all(d["source_doi"]==first["doi"] and d["source_year"]==first["year"] and d["checkpoint"]==CHECKPOINT_SHA for d in qualifying),"Unverified formulation provenance")
            check(r["in_pool"]==(bool(good) or r["paper_vote"]>0),"Pool differs from required union")
            check(r["in_pool"]==("pool_rank" in r),"Admitted material missing rank")
            counts["qualified"]+=bool(good);counts["qualified_admitted"]+=bool(good) and r["in_pool"]
            counts["qualified_recipes"]+=len(good);counts["hpg_only"]+=bool(good) and r["paper_vote"]<=0
        for slot,scope in (("paper_decisions","paper"),("physical_decisions","physical")):
            judged=set()
            for sha in f[slot]:
                d=pins[sha];check(d["cutoff"]==y and d["mode"]==scope,"Cross-window decision")
                check(bool(d["lookups"]) and bool(d["receipts"]),"Missing real tool call")
                judged.update(d["judgments"]);requests.update(("controller",key) for key in d["receipts"])
            check(judged==(set(panel) if scope=="paper" else set(panel)&grid["designs"].keys()),"Controller coverage missing")
        windows.append(counts)
        if y==YEARS[-1]:
            check(not (home/str(y)/"reveal.json").exists(),"Open window has unexpected labels");continue
        last_feedback=verified(home/str(y)/"reveal.json")
        check(f["sha256"]==last_feedback["forecast"] and moment(f)<=moment(last_feedback),"Revealed before freeze")
        check(all(y<e["year"]<=y+5 for v in last_feedback["events"].values() for e in v),"Event outside target window")
    recent=verified(home/str(YEARS[-1])/"forecast.json")
    for y in YEARS:
        b=verified(home/"external_verification"/f"{y}.json");check(moment(recent)<=moment(b),"Held-out search opened before final freeze")
        for v in b["events"].values():references.update(e["doi"] for e in v)
    check(not references.intersection(covered["broad"]|covered["spe"]),"DOI overlap in independent verification")
    for channel,key in requests:
        obj=verified(RUN/"calls"/channel/(key+".response.json"))
        req=read_json(RUN/"calls"/channel/(key+".request.json"))
        check(obj["http_status"]==200 and obj["provider_id"] and obj["request"]==fingerprint(req)==key and obj["model"]==protocol["model"],"Model receipt mismatch")
    report={"coverage":{k:len(v) for k,v in covered.items()},"windows":windows,
         "unique_real_model_responses":len(requests),"future_label_timing":"verified",
         "input_checks":"exact DOI coverage, material & recipe equality, past source and checkpoint, independent DOI disjointness"}
    registered=ROOT/"runs"/"five_windows"
    if home.name=="adoption" and (registered/str(YEARS[-1])/"forecast.json").exists():
        same=0
        def receipt_index(path):
            ix={}
            for f in (path/"decisions").rglob("*.json"):
                d=verified(f);ix[d["sha256"]]=d["receipts"]
            return ix
        original_receipts=receipt_index(registered)
        for y in YEARS:
            old=verified(registered/str(y)/"forecast.json");new=verified(home/str(y)/"forecast.json")
            check(old["rankings"]==new["rankings"] and old["policy"]==new["policy"],"Replay changed an actual forecast")
            for k in ("physical_decisions","paper_decisions"):
                # Sealing dates of local batches differ. Underlying provider request hashes and genuine decisions must match.
                first=sorted(key for h in old[k] for key in original_receipts[h])
                replay=sorted(key for h in new[k] for key in pins[h]["receipts"])
                check(first==replay,"Replay changed provider evidence")
            same+=len(old["rankings"])
        report["same_rankings_as_original_live_study"]=same
    directory=ROOT/"results" if home.name=="adoption" else home/"results"
    write_json(directory/"verification.json",report)
    print("Verified all five windows,",len(requests),"real provider responses;",sum(w["qualified_admitted"] for w in windows),"/",sum(w["qualified"] for w in windows),"high material-window forecasts")


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id",default="adoption")
    audit(ROOT/"runs"/parser.parse_args().run_id)
