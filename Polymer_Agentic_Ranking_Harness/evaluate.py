"""Open post-cutoff labels and archived comparators only after all five forecasts have been sealed."""
import csv
from collections import defaultdict
from itertools import groupby
from math import ceil, exp, log1p
from os import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from evidence import (ROOT,SOURCE,INTERVALS,YEARS,DATA,AXES,normalized,observations,read_interval,
                      seal,verified,write_json)
from ordinal import positions
from evidence_order import constrained_tiers
from ranking_policy import EXPOSURE, registered_policy

PRIMARY_COMPARATORS=("exposure_primary","llm_unconstrained","exposure_fronts","previous","frequency_recency")
ORDINAL_COMPARATORS=("agent","previous","frequency_recency")


def metrics(scores,positive):
    names=sorted(scores,key=lambda n:-scores[n])
    positives=set(names)&set(positive)
    total=len(positives);seen=hits=0;area=top=top20=0.
    for _,items in groupby(names,key=lambda n:scores[n]):
        block=list(items);m=len(block);c=len(set(block)&positives)
        if c:
            for j in range(1,m+1):
                earlier=(j-1)*(c-1)/(m-1) if m>1 else 0.
                area+=(c/m)*(hits+1+earlier)/(seen+j)
        top+=c*min(m,max(0,10-seen))/m
        top20+=c*min(m,max(0,ceil(len(scores)*0.2)-seen))/m
        hits+=c;seen+=m
    return {"candidates":len(names),"observed":total,"AP":area/total if total else None,"hits_at_10":top,
            "recall_at_20pct":top20/total if total else None}


def write_table(path,rows,fields=()):
    cols=list(rows[0]) if rows else list(fields)
    path.parent.mkdir(parents=True,exist_ok=True)
    staging=None
    try:
        with NamedTemporaryFile("w",dir=path.parent,encoding="utf-8-sig",newline="",delete=False) as stream:
            staging=Path(stream.name)
            table=csv.DictWriter(stream,fieldnames=cols)
            table.writeheader()
            table.writerows(rows)
        replace(staging,path)
    finally:
        if staging is not None:
            staging.unlink(missing_ok=True)


def rank_intervals(scores):
    ordered = sorted(scores, key=lambda name: -scores[name])
    tiers = [list(tied) for _, tied in groupby(ordered, key=scores.__getitem__)]
    return positions(tiers)


def hpg_coverage(designs, qualifying):
    predicted=sum(d["status"]=="predicted" for d in designs)
    if qualifying:
        status="passed_threshold"
    elif predicted:
        status="below_threshold_on_computed_recipes"
    elif designs:
        status="no_valid_prediction"
    else:
        status="no_registered_design"
    return {"hpg_status":status,"hpg_predicted_conditions":predicted,"hpg_registered_conditions":len(designs)}


def cutoff_sources(graph,broad):
    material_dois=defaultdict(set);abstract_dois=defaultdict(set);roles=defaultdict(set)
    for doi,doc in graph["publications"].items():
        if doc["stage"]!="general_polymer":
            continue
        for entry in doc["items"]:
            name=entry["material"]
            material_dois[name].add(doi)
            roles[name].update(entry["axes"])
            if "S1" in broad[doi]["segments"]:
                abstract_dois[name].add(doi)
    return {n:{"historical_source_dois":"|".join(sorted(dois)), "source_dois_with_abstract":len(abstract_dois[n]),
               "directly_extracted_axes":"|".join(axis for axis in AXES if axis in roles[n])}
            for n,dois in material_dois.items()}


def observed_comparisons(year, source, names, events, rows, methods,primary_method="agent"):
    positive_names = set(names) & events.keys()
    intervals = {method: rank_intervals(scores) for method, scores in methods.items()}
    columns=PRIMARY_COMPARATORS if primary_method=="exposure_primary" else ORDINAL_COMPARATORS
    for name in sorted(positive_names, key=lambda n: (intervals[primary_method][n], n)):
        evidence = sorted(events[name], key=lambda e: (e["year"], e["doi"]))
        item = {"cutoff": year, "verification_source": source, "material": name,
                "eligible_candidates": len(names), "pre_cutoff_source_dois": rows[name]["source_count"],
                "admitted_via": rows[name]["route"], "qualifying_HPG_recipes": len(rows[name]["qualifying_recipes"])}
        for method in columns:
            lo, hi = intervals[method][name] if method in intervals else (None, None)
            item[method+"_rank_min"], item[method+"_rank_max"] = lo, hi
        item["first_observed_year_in_window"] = evidence[0]["year"]
        item["observed_roles"] = "|".join(sorted({e["role"] for e in evidence}))
        item["verification_dois"] = "|".join(sorted({e["doi"] for e in evidence}))
        yield item


def same_exposure_pairs(year, source, names, events, rows, methods):
    """Compare materials with identical document counts and latest publication years."""
    blocks = defaultdict(list)
    for name in names:
        blocks[rows[name]["source_count"], rows[name]["latest_source"]].append(name)
    for method,scores in methods.items():
        wins = ties = losses = positives = 0
        for group in blocks.values():
            observed = [n for n in group if n in events]
            unobserved = [n for n in group if n not in events]
            if not unobserved:
                continue
            positives += len(observed)
            for name in observed:
                for other in unobserved:
                    wins += scores[name] > scores[other]
                    ties += scores[name] == scores[other]
                    losses += scores[name] < scores[other]
        pairs = wins+ties+losses
        yield {"cutoff":year, "verification_source":source, "method":method,
               "observed_with_exposure_peers":positives, "pairs":pairs, "ahead":wins, "tied":ties, "behind":losses,
               "concordance":(wins+0.5*ties)/pairs if pairs else None}


def external_labels(home,excluded):
    freezes=[verified(home/str(y)/"forecast.json")["sha256"] for y in YEARS]
    prior=set();out={}
    for lo,hi in INTERVALS:
        inp=read_interval("independent",lo,hi)
        filtered={n:r for n,r in inp["records"].items() if n not in excluded}
        events=observations(filtered,hi)
        out[hi]=seal(home/"verification"/f"{hi}.json",{"interval":[lo,hi],"forecasts":freezes,"input":inp["sha256"],
                "disjoint_papers":len(filtered),"events":events,"earlier":sorted(prior)})
        prior.update(events)
    return out


def evaluate(home,broad,past):
    policy=registered_policy(verified(home/"protocol.json"))
    official=policy==EXPOSURE
    primary_method="exposure_primary" if official else "agent"
    held=external_labels(home,set(broad)|set(past))
    table=[];counts=[];rankings=[];pooled=[];history=[];comparability={};coverage=[];paired=[];matched=[]
    grid=verified(DATA/"physics/grid.json")
    for y in YEARS:
        snap=verified(home/str(y)/"forecast.json");rows=snap["rows"]
        graph=verified(home/str(y)/"graph.json")
        if official:
            fronts=positions(constrained_tiers(rows,use_agent=False))
            preferences=verified(home/str(y)/"comparisons.json")["tiers"]
            provenance=cutoff_sources(graph,broad)
        axes={k:set() for k in AXES};triples=set();analogues=set();target_axis={}
        for n,records in graph["known_SPE"].items():
            for ev in records:
                for k,val in ev["axes"].items():target_axis.setdefault((k,normalized(val)),set()).add(n)
        for doc in graph["publications"].values():
            if doc["stage"]!="general_polymer":continue
            for ev in doc["items"]:
                n=ev["material"];facts=ev["axes"]
                for k,val in facts.items():
                    axes[k].add(n)
                    if target_axis.get((k,normalized(val)),set())-{n}:analogues.add(n)
                if all(k in facts for k in AXES):triples.add(n)
        coverage.append({"cutoff":y,"candidates":len(rows),"papers":len(graph["publications"]),
                         "papers_with_abstract_excerpts":sum("S1" in broad[d]["segments"] for d in graph["publications"]),
                         "single_source_materials":sum(r["source_count"]==1 for r in rows.values()),
                         **{k:len(v) for k,v in axes.items()},"three_axes_in_same_evidence_row":len(triples),
                         "with_exact_axis_analogue_in_past_SPE":len(analogues),"HPG_evaluable":len(rows.keys()&grid["designs"].keys())})
        prev=SOURCE/"runs"/"adoption"/str(y)/"forecast.json"
        older=verified(prev)["rankings"] if prev.exists() else None
        comparable=older is not None and older.keys()==rows.keys()
        comparability[y]=comparable
        pool={n for n,r in rows.items() if r["in_pool"]}
        raw_in_pool=positions(preferences,pool) if official else {}
        oldpool={n for n in rows if older[n]["in_pool"]} if comparable else set()
        high={n for n,r in rows.items() if r["qualifying_recipes"]}
        by_stratum={};by_stratum_pool={}
        for target in ("first_observed","repeat"):
            eligible={n for n,r in rows.items() if r["stratum"]==target}
            by_stratum.update(positions(snap["tiers"],eligible))
            by_stratum_pool.update(positions(snap["tiers"],eligible&pool))
        external={};primary={}
        if y<YEARS[-1]:
            revealed=verified(home/str(y)/"reveal.json")
            if revealed["forecast"]!=snap["sha256"]:raise ValueError("Wrong outcome binding")
            primary=revealed["events"];external=held[y+5]["events"]
            history.append(revealed["memory"])
            for source,events,other_prior in (("primary",primary,()),("disjoint",external,held[y+5]["earlier"])):
                for target in ("first_observed","any_use"):
                    cohort={n for n,r in rows.items() if target=="any_use" or (r["stratum"]=="first_observed" and n not in other_prior)}
                    pos=cohort & events.keys()
                    populations={"whole_panel":cohort,"agent_pool":cohort&pool}
                    if comparable:populations["previous_fixed_pool"]=cohort&oldpool
                    for subset,names in populations.items():
                        arms={primary_method:{n:-rows[n]["rank_min"] for n in names}}
                        if official:
                            arms["llm_unconstrained"]={n:-rows[n]["llm_rank_min"] for n in names}
                            arms["exposure_fronts"]={n:-fronts[n][0] for n in names}
                            # Same historical bibliographic comparator, available even without the old experiment.
                            arms["frequency_recency"]={n:0.30*log1p(rows[n]["source_count"])+0.25*exp(-(y-rows[n]["latest_source"])/8) for n in names}
                        if comparable:
                            arms.update(previous={n:older[n]["score"] for n in names},
                                        frequency_recency={n:older[n]["base_score"] for n in names})
                        if target=="first_observed" and subset=="whole_panel":
                            paired.extend(observed_comparisons(y,source,names,events,rows,arms,primary_method))
                            matched.extend(same_exposure_pairs(y,source,names,events,rows,arms))
                        for method,scores in arms.items():
                            table.append({"cutoff":y,"source":source,"target":target,"universe":subset,
                                          "method":method,**metrics(scores,pos)})
                    pooled.append({"cutoff":y,"source":source,"target":target,"observed":len(pos),
                         "agent_pool_size":len(cohort&pool),"agent_pool_hits":len(pos&pool),
                         "previous_pool_size":len(cohort&oldpool) if comparable else None,
                         "previous_pool_hits":len(pos&oldpool) if comparable else None})
        sizes=[len(t) for t in snap["tiers"]]
        counts.append({"cutoff":y,"candidates":len(rows),"agent_pool":len(pool),"previous_pool":len(oldpool) if comparable else None,
                       "qualifying_hpg":len(high),"qualifying_admitted":len(high&pool),"hpg_only":sum(rows[n]["route"]=="hpg_only" for n in high),
                       "tiers":len(sizes),"largest_tie":max(sizes,default=0),"materials_with_shared_rank":sum(s for s in sizes if s>1),
                       "forecast_status":"closed" if y<YEARS[-1] else f"open_{y+1}_{y+5}"})
        for tier in snap["tiers"]:
            for n in sorted(tier):
                r=rows[n];p=r["pool_rank"] or (None,None)
                nominations=r["paper_nomination"] or {}
                ranked={"cutoff":y,"material":n,"rank_min":r["rank_min"],"rank_max":r["rank_max"],
                      "in_pool":r["in_pool"],"pool_rank_min":p[0],"pool_rank_max":p[1],"route":r["route"],
                      "stratum":r["stratum"],"stratum_rank_min":by_stratum[n][0],"stratum_rank_max":by_stratum[n][1],
                      "stratum_pool_rank_min":by_stratum_pool.get(n,(None,None))[0],"stratum_pool_rank_max":by_stratum_pool.get(n,(None,None))[1],
                      "source_papers":r["source_count"],"paper_nomination_doi":nominations.get("doi",""),
                      "paper_nomination_reason":nominations.get("reason",""),
                      "hpg_passed_conditions":len(r["qualifying_recipes"]),
                      "max_qualifying_sigma_S_cm":max((d["sigma_S_cm"] for d in r["qualifying_recipes"]),default=None),
                      "qualifying_temperatures_C":"|".join(map(str,sorted({d["temperature_C"] for d in r["qualifying_recipes"]}))),
                      "observed_primary_dois":"|".join(sorted({e["doi"] for e in primary.get(n,[])})) if y<YEARS[-1] else None,
                      "observed_disjoint_dois":"|".join(sorted({e["doi"] for e in external.get(n,[])})) if y<YEARS[-1] else None}
                if official:
                    local_raw=raw_in_pool.get(n,(None,None))
                    ranked.update(primary_ranking=policy,latest_source_year=r["latest_source"],
                                  llm_rank_min=r["llm_rank_min"],llm_rank_max=r["llm_rank_max"],
                                  llm_pool_rank_min=local_raw[0],llm_pool_rank_max=local_raw[1],
                                  **provenance[n],
                                  **hpg_coverage(grid["designs"].get(n,[]),r["qualifying_recipes"]))
                rankings.append(ranked)
    out=home/"results"
    write_table(out/"rankings.csv",rankings)
    write_table(out/"adoption_pool.csv",[r for r in rankings if r["in_pool"]],list(rankings[0]) if rankings else ())
    write_table(out/f"{YEARS[-1]}_first_adoption.csv",[r for r in rankings if r["cutoff"]==YEARS[-1] and r["in_pool"] and r["stratum"]=="first_observed"],
                list(rankings[0]) if rankings else ())
    write_table(out/"metrics.csv",table);write_table(out/"pool_coverage.csv",pooled);write_table(out/"windows.csv",counts)
    write_table(out/"evidence_coverage.csv",coverage)
    paired_methods=PRIMARY_COMPARATORS if official else ORDINAL_COMPARATORS
    paired_fields=["cutoff","verification_source","material","eligible_candidates","pre_cutoff_source_dois","admitted_via","qualifying_HPG_recipes",
                   *(f"{method}_rank_{bound}" for method in paired_methods for bound in ("min","max")),
                   "first_observed_year_in_window","observed_roles","verification_dois"]
    write_table(out/"observed_first_use_ranks.csv",paired,paired_fields)
    write_table(out/"same_exposure_pairs.csv",matched)
    write_json(out/"summary.json",{"windows":counts,"metrics":table,"pool_coverage":pooled,
               "comparability":comparability,"evidence_coverage":coverage,"historical_memory":history,
               "disjoint_papers":sum(v["disjoint_papers"] for v in held.values()),
               **({"primary_ranking":policy,"primary_metric_method":primary_method} if official else {})})
    if not official:
        from evidence_order import run as evaluate_exposure_constraint
        evaluate_exposure_constraint(home)
    from report import render
    render(home)
    print("RESULTS",out,flush=True)
