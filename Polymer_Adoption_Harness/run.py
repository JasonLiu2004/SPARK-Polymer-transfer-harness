"""Chronological experiment: learn only after freezing each historical forecast."""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from common import DATA,ROOT,RUN,YEARS,Model,file_hash,seal,verified,writer
from corpus import INTERVALS,TOPIC,papers
from extract import read_interval
from graph import build,observations
from controller import run_controller
from physics import DEFAULT_THRESHOLD,GRID,CHECKPOINT_SHA,dated_predictions,prepare
from adoption import learn,ranked,seed


def put(records,interval):
    for doi,p in interval["records"].items():
        if doi in records and records[doi]!=p:raise ValueError("Conflicting publication identity")
        records[doi]=p


def study(home,threshold,workers):
    import math
    if not math.isfinite(threshold) or threshold<=0:raise ValueError("Threshold in S/cm must be finite and positive")
    model=Model(RUN/"calls"/"controller")
    files=("common.py","corpus.py","extract.py","structures.py","physics.py","graph.py","adoption.py","controller.py","run.py")
    old_entry=home/"registered_source"/"run.py"
    source_hashes={f:file_hash(old_entry if f=="run.py" and old_entry.exists() else ROOT/f) for f in files}
    protocol=seal(home/"protocol.json",{"years":YEARS,"grid":GRID,"threshold_S_cm":threshold,
        "checkpoint":CHECKPOINT_SHA,"model":model.model,"supplement_query":TOPIC,
        "rule":"literature nomination OR any source-backed valid HPG design meeting the inclusive threshold",
        "outcome":"next-window independently indexed observed solid sample or tested solid device, matched named polymer",
        "code":source_hashes})
    grid=prepare();broad={};target={};policy=seed(YEARS[0]);previous=None
    seed_data=read_interval("spe",*INTERVALS[0],workers);put(target,seed_data)
    for lo,year in INTERVALS:
        section=home/str(year)
        incoming=read_interval("broad",lo,year,workers);put(broad,incoming)
        if policy["through"]!=year:raise ValueError("Policy/window mismatch")
        ledger,panel=build(broad,year);known=observations(target,year)
        graph=seal(section/"graph.json",{"cutoff":year,"previous":previous,"broad_snapshot":incoming["sha256"],
            "source_papers":len(broad),"new_papers":len(incoming["records"]),"publications":ledger,
            "past_spe":known})
        previous=graph["sha256"]
        path=section/"forecast.json"
        if path.exists():
            forecast=verified(path)
            if forecast["protocol"]!=protocol["sha256"] or forecast["graph"]!=previous or forecast["policy"]!=policy:
                raise ValueError("Frozen forecast does not match state")
        else:
            dated=dated_predictions(panel,grid,year)
            paper,p_log=run_controller("paper",panel,dated,policy,year,threshold,workers,home)
            physical,h_log=run_controller("physical",panel,dated,policy,year,threshold,workers,home)
            ranking=ranked(panel,paper,physical,dated,known,policy,year,threshold)
            forecast=seal(path,{"protocol":protocol["sha256"],"cutoff":year,"graph":previous,
                "policy":policy,"hpg_grid":grid["sha256"],"threshold_S_cm":threshold,
                "paper_decisions":p_log,"physical_decisions":h_log,"rankings":ranking})
        print("FROZEN",year,len(panel),"candidates;",sum(r["in_pool"] for r in forecast["rankings"].values()),"in pool",flush=True)
        if year==YEARS[-1]:continue
        reveal=read_interval("spe",year+1,year+5,workers);events=observations(reveal["records"],year+5)
        policy,pairs=learn(forecast,events,policy,year+5)
        seal(section/"reveal.json",{"forecast":forecast["sha256"],"interval":[year+1,year+5],"spe_input":reveal["sha256"],
             "spe_papers":len(reveal["records"]),"events":events,"pairs":pairs,"updated_policy":policy})
        put(target,reveal)
    # This retrieval was never used to build the graph or the policy. Open it only after all five freezes.
    frozen=[verified(home/str(y)/"forecast.json")["sha256"] for y in YEARS]
    disjoint=set(broad)|set(target);prior={}
    for lo,hi in INTERVALS:
        source=read_interval("independent",lo,hi,workers)
        filtered={k:p for k,p in source["records"].items() if k not in disjoint}
        ev=observations(filtered,hi)
        seal(home/"external_verification"/f"{hi}.json",{"freezes":frozen,"interval":[lo,hi],
             "input":source["sha256"],"papers":len(filtered),"excluded_overlap":len(source["records"])-len(filtered),
             "earlier_materials":sorted(prior),"events":ev})
        for n,rows in ev.items():prior.setdefault(n,[]).extend(rows)
    from results import export
    export(home)


if __name__=="__main__":
    if "--legacy" not in sys.argv[1:]:
        entry=ROOT.parent/"Polymer_Agentic_Ranking_Harness"/"run.py"
        raise SystemExit(subprocess.call([sys.executable,"-X","utf8","-B",str(entry),*sys.argv[1:]]))
    sys.argv.remove("--legacy")
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--threshold",type=float,default=DEFAULT_THRESHOLD,help="inclusive, S/cm")
    p.add_argument("--workers",type=int,default=24)
    p.add_argument("--run-id",default="adoption")
    p.add_argument("--offline",action="store_true",help="require verified prior provider responses, with no language-model network calls")
    a=p.parse_args()
    if not re.fullmatch(r"[\w-]+",a.run_id) or not 1<=a.workers<=64:p.error("Invalid run ID or workers")
    if a.offline:os.environ["POLYMER_ADOPTION_OFFLINE"]="1"
    home=ROOT/"runs"/a.run_id
    with writer(home):study(home,a.threshold,a.workers)
