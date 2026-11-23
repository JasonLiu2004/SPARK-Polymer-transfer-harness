"""Roll the independent polymer corpus forward by five years and ask the agent to order all materials."""
import argparse
import math
import os
import re
from evidence import (ROOT,SOURCE,INTERVALS,YEARS,DEFAULT_THRESHOLD,Model,Evidence,admit,
                      file_hash,merge_interval,observations,prepare,read_interval,seal,verified,writer)
from agent import Agent
from ordinal import CHUNK,LANDMARKS,LEAF,rank_all,screen
from memory import reflect
from ranking_policy import (DEFAULT_RUN, EXPOSURE, ORDINAL, POLICIES, implementation_path,
                            ranking_record, select_policy)


def window_agent(section,view,memory,model_name):
    model=Model(section.parent.parent/"provider")
    if model.offline:
        model.model=model_name
    elif model.model!=model_name:
        raise ValueError("Configured model differs from the forecast protocol")
    return Agent(section,view,memory,model)


def study(home,threshold,workers,requested_policy=None):
    if not math.isfinite(threshold) or threshold<=0:
        raise ValueError("threshold must be finite and positive, in S/cm")
    policy=select_policy(home,requested_policy)
    files=["agent.py","evidence.py","memory.py","ordinal.py","run.py"]
    if policy==EXPOSURE:
        files.extend(["ranking_policy.py","evidence_order.py"])
    code={name:file_hash(implementation_path(name,policy)) for name in files}
    upstream={n:file_hash(SOURCE/n) for n in ("common.py","corpus.py","structures.py","graph.py","physics.py","adoption.py","extract.py")}
    grid=prepare()
    existing=home/"protocol.json"
    cached_model=existing.exists() and os.environ.get("POLYMER_ADOPTION_OFFLINE")=="1"
    model_name=verified(existing)["model"] if cached_model else Model(home.parent/"provider").model
    registration={"cutoffs":YEARS,"model":model_name,
                 "threshold_S_cm":threshold,"own_code":code,"upstream_code":upstream,"hpg_grid":grid["sha256"],
                 "scheduler":{"leaf":LEAF,"landmark_sample":LANDMARKS,"placement_batch":CHUNK},
                 "outcome":"named material used in a solid polymer electrolyte during the next five years",
                 "admission":"new independent agent literature nomination OR any dated qualifying HPG design",
                 "rank":"LLM ordinal tiers and relative placements, with ties",
                 "memory":"LLM evidence questions induced after each historical forecast is sealed",
                 "evaluation":"primary and DOI-disjoint SPE; first-observed and any use; tie-aware AP and hits@10 on all names and on the previous fixed pool; separately report new-pool coverage and size",
                 "comparators":"previous frozen independent-agent scores and paper-frequency/recency baseline read only by evaluation"}
    if policy==EXPOSURE:
        registration.update(primary_ranking=policy,
            rank="Dominance by distinct pre-cutoff source DOIs and latest source year; among eligible candidates choose the best submitted LLM tier",
            memory="Reflect on the frozen PRIMARY order. Cases include the unconstrained LLM position and the actual dated publication exposure",
            controls="The raw agent tiers and neutral exposure tiers are evaluation controls on the same panel and admission pool")
    protocol=seal(existing,registration)
    broad={};past={};memory=[];previous=None
    merge_interval(past,read_interval("spe",*INTERVALS[0],workers))
    for first,year in INTERVALS:
        section=home/str(year)
        source=read_interval("broad",first,year,workers)
        merge_interval(broad,source)
        view=Evidence(year,broad,past,grid,threshold)
        graph=seal(section/"graph.json",{"cutoff":year,"previous":previous,"new_input":source["sha256"],
                   "visible_papers":len(broad),"publications":view.ledger,"known_SPE":view.known,"digest":view.digest})
        previous=graph["sha256"]
        # A completed forecast can be opened even on a computer without an active API configuration.
        agent=None
        path=section/"forecast.json"
        if path.exists():
            f=verified(path)
            if (f["protocol"],f["graph"],f["memory"])!=(protocol["sha256"],graph["sha256"],memory):
                raise ValueError("Frozen forecast belongs to another protocol, graph or memory")
        else:
            agent=window_agent(section,view,memory,model_name)
            print("READ",year,len(view.panel),"materials",flush=True)
            nominees,intakes=screen(agent,view.panel,workers)
            pool=admit(nominees,view.physical,year,threshold)
            preferences,nodes=rank_all(agent,list(view.panel),workers)
            tiers,full,admitted,raw=ranking_record(policy,preferences,view.panel,year,pool)
            rows={}
            for n,(lo,hi) in full.items():
                item=view.panel[n];entry=pool.get(n,{})
                rows[n]={"rank_min":lo,"rank_max":hi,"pool_rank":admitted.get(n),"in_pool":n in pool,
                         "paper_nomination":nominees.get(n),"route":entry.get("route","outside"),
                         "qualifying_recipes":entry.get("qualifying_recipes",[]),
                         "source_count":item["papers"],"latest_source":item["latest"],
                         "stratum":"repeat" if view.known.get(n) else "first_observed"}
                if policy==EXPOSURE:
                    rows[n]["llm_rank_min"],rows[n]["llm_rank_max"]=raw[n]
            tree=seal(section/"comparisons.json",{"cutoff":year,"nodes":nodes,"intake":intakes,"tiers":preferences})
            f=seal(path,{"protocol":protocol["sha256"],"cutoff":year,"horizon":[year+1,year+5],"graph":graph["sha256"],
                         "comparison_tree":tree["sha256"],"memory":memory,"tiers":tiers,"rows":rows,
                         **({"primary_ranking":policy} if policy==EXPOSURE else {})})
        print("FROZEN",year,len(f["rows"]),len(f["tiers"]),"tiers",sum(r["in_pool"] for r in f["rows"].values()),"in pool",flush=True)
        if year==YEARS[-1]:continue
        reveal=read_interval("spe",year+1,year+5,workers)
        events=observations(reveal["records"],year+5)
        path=section/"reveal.json"
        if path.exists():
            update=verified(path)
            if update["forecast"]!=f["sha256"] or update["spe_input"]!=reveal["sha256"]:
                raise ValueError("Historical feedback mismatch")
        else:
            if agent is None:
                agent=window_agent(section,view,memory,model_name)
            learned,trace,cases=reflect(agent,f,events)
            update=seal(path,{"forecast":f["sha256"],"spe_input":reveal["sha256"],"interval":[year+1,year+5],
                              "events":events,"training_cases":cases,"decision":trace,"memory":learned})
        memory=memory+[update["memory"]]
        merge_interval(past,reveal)
    from evaluate import evaluate
    evaluate(home,broad,past)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold",type=float,default=DEFAULT_THRESHOLD)
    parser.add_argument("--workers",type=int,default=24)
    parser.add_argument("--ranking",choices=POLICIES,
                        help="Primary forecast method. New runs default to exposure. Existing runs keep their registered method.")
    parser.add_argument("--run-id",help="Defaults to exposure_primary, or ordinal for --ranking ordinal")
    parser.add_argument("--offline",action="store_true")
    args=parser.parse_args()
    run_id=args.run_id or ("ordinal" if args.ranking==ORDINAL else DEFAULT_RUN)
    if not re.fullmatch(r"[\w-]+",run_id) or not 1<=args.workers<=64:parser.error("Invalid run ID or worker count")
    if args.offline:os.environ["POLYMER_ADOPTION_OFFLINE"]="1"
    home=ROOT/"runs"/run_id
    with writer(home):study(home,args.threshold,args.workers,args.ranking)


if __name__=="__main__":main()
