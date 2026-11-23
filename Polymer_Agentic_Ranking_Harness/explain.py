"""Trace a named material's actual relative comparisons, source citations and HPG admission."""
import argparse
import json
from evidence import ROOT,verified
from ordinal import positions
from ranking_policy import DEFAULT_RUN, EXPOSURE, ORDINAL


def recommendations(home,year,stratum="first_observed"):
    """Read the sealed recommendation pool immediately, without opening any outcome or evaluation file."""
    if stratum not in {"first_observed","repeat","all"}:
        raise ValueError("Unknown adoption stratum")
    forecast=verified(home/str(year)/"forecast.json")
    rows=forecast["rows"]
    selected={n for n,r in rows.items() if r["in_pool"] and (stratum=="all" or r["stratum"]==stratum)}
    ranks=positions(forecast["tiers"],selected)
    candidates=[]
    for tier in forecast["tiers"]:
        for name in sorted(selected.intersection(tier)):
            row=rows[name]
            candidates.append({"material":name,"rank_in_selection":ranks[name],
                               "full_rank":[row["rank_min"],row["rank_max"]],"pool_rank":row["pool_rank"],
                               "stratum":row["stratum"],"route":row["route"],"paper_nomination":row["paper_nomination"],
                               "qualifying_recipes":row["qualifying_recipes"]})
    return {"cutoff":year,"horizon":forecast["horizon"],"primary_ranking":forecast.get("primary_ranking",ORDINAL),
            "forecast_sha256":forecast["sha256"],"stratum":stratum,"count":len(candidates),"candidates":candidates}


def publication_precedence(name,rows,graph):
    row=rows[name]
    count,year=row["source_count"],row["latest_source"]
    blockers=[n for n,r in rows.items() if r["source_count"]>=count and r["latest_source"]>=year
              and (r["source_count"],r["latest_source"])!=(count,year)]
    last=max((rows[n]["rank_max"] for n in blockers),default=0)
    witnesses=sorted(n for n in blockers if rows[n]["rank_max"]==last)[:3]
    sources={n:[] for n in [name,*witnesses]}
    for doi,doc in graph["publications"].items():
        if doc["stage"]!="general_polymer":
            continue
        for n in {ev["material"] for ev in doc["items"]} & sources.keys():
            if doc["year"]==rows[n]["latest_source"]:
                sources[n].append(doi)
    def describe(n):
        return {"material":n,"distinct_dois":rows[n]["source_count"],"latest_year":rows[n]["latest_source"],
                "latest_source_dois":sorted(sources[n]),"primary_rank":[rows[n]["rank_min"],rows[n]["rank_max"]]}
    return {"coverage":describe(name),"materials_required_ahead":len(blockers),
            "first_position_eligible":last+1,"actual_start_position":row["rank_min"],
            "examples_of_last_required_predecessors":[describe(n) for n in witnesses]}


def trace(home,year,name):
    section=home/str(year);forecast=verified(section/"forecast.json")
    if name not in forecast["rows"]:raise ValueError("Material is absent from this frozen panel: "+name)
    comparison=verified(section/"comparisons.json")
    if comparison["sha256"]!=forecast["comparison_tree"]:
        raise ValueError("Comparison trace differs from the frozen forecast")
    nodes=comparison["nodes"];path="root";steps=[]
    def load(mode,key):return verified(section/"decisions"/mode/(key+".json"))
    def step(mode,d,description):
        a=d["result"]
        return {"mode":mode,"contract":d["contract"],"decision":description,
                "comparison_reason_for_group":a.get("because"),"cited_dois_by_material":a.get("evidence",{}),
                "repair_subdecisions":d.get("subdecisions",[])}
    while True:
        node=nodes[path]
        if "tiers" in node:
            if node["direct"]:
                d=load("order",node["direct"][0])
                steps.append(step("listwise",d,{"ordered_tiers":d["result"]["tiers"]}))
            break
        anchors=load("order",node["landmark_decision"])
        tiers=anchors["result"]["tiers"]
        slot=next(("E"+str(i) for i,t in enumerate(tiers,1) if name in t),None)
        if slot is not None:
            steps.append(step("landmark",anchors,{"landmarks_high_to_low":tiers,"own_slot":slot}))
            break
        matched=False
        for key in node["placements"]:
            d=load("place",key);allocation=d["result"]["placements"]
            if name not in allocation:continue
            slot=allocation[name];matched=True
            steps.append(step("relative_to_landmarks",d,{"landmarks_high_to_low":d["landmarks"],"own_slot":slot}))
            break
        if not matched:raise ValueError("Missing logged comparison")
        if slot.startswith("E"):break
        path+="/"+slot
    row=forecast["rows"][name]
    result={"material":name,"cutoff":year,"years_forecast":forecast["horizon"],"full_rank":[row["rank_min"],row["rank_max"]],
            "pool_rank":row["pool_rank"],"route":row["route"],"observed_prior":row["stratum"]=="repeat",
            "qualifying_recipes":row["qualifying_recipes"],"literature_nomination":row["paper_nomination"],
            "comparisons":steps}
    if forecast.get("primary_ranking")==EXPOSURE:
        graph=verified(section/"graph.json")
        if graph["sha256"]!=forecast["graph"]:
            raise ValueError("The dated graph differs from the frozen forecast")
        rows=forecast["rows"]
        stratum={n for n,r in rows.items() if r["stratum"]==row["stratum"]}
        admitted={n for n,r in rows.items() if r["in_pool"]}
        raw=positions(comparison["tiers"])[name]
        if raw!=(row["llm_rank_min"],row["llm_rank_max"]):
            raise ValueError("Raw LLM position differs from its evidence trace")
        result.update(primary_ranking=EXPOSURE,llm_preference_rank=list(raw),
                      llm_preference_pool_rank=positions(comparison["tiers"],admitted).get(name),
                      stratum=row["stratum"],primary_stratum_rank=positions(forecast["tiers"],stratum)[name],
                      primary_stratum_pool_rank=positions(forecast["tiers"],stratum&admitted).get(name),
                      publication_precedence=publication_precedence(name,rows,graph))
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--run-id",default=DEFAULT_RUN)
    p.add_argument("--year",type=int,required=True)
    view=p.add_mutually_exclusive_group(required=True)
    view.add_argument("--material",help="Inspect the ranking evidence for one named material")
    view.add_argument("--pool",action="store_true",help="Return the complete recommendation pool for the selected stratum")
    p.add_argument("--stratum",choices=("first_observed","repeat","all"),help="Used with --pool; default first_observed")
    args=p.parse_args()
    if args.stratum and not args.pool:p.error("--stratum applies to --pool")
    home=ROOT/"runs"/args.run_id
    result=recommendations(home,args.year,args.stratum or "first_observed") if args.pool else trace(home,args.year,args.material)
    print(json.dumps(result,ensure_ascii=False,indent=2))
