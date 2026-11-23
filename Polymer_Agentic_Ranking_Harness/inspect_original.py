"""Read-only SPARK method check. This module is used separately from the independent forecasting pipeline."""
import json
import math
import statistics
from itertools import groupby
from pathlib import Path

ROOT=Path(__file__).resolve().parent
PACKAGE=ROOT.parent/"SPARK_selected3_seed_shareable_20260807"/"SPARK_selected3_seed_shareable_20260807"


def percentiles(values):
    order=sorted(values,key=values.get);result={};start=0
    for _,items in groupby(order,key=values.get):
        group=list(items)
        percentile=(start+(len(group)-1)/2)/(len(order)-1) if len(order)>1 else 1.
        result.update(dict.fromkeys(group,percentile));start+=len(group)
    return result


def property_modifier(row):
    c=row["r42_planner_config"];p=row["conductivity_threshold_probability"]
    s,u=row["property_support"],row["property_uncertainty"];r=s*(1-u)
    if (not row["r42_property_global_gate_enabled"] or p is None or s<c["minimum_property_support"] or
            u>c["maximum_property_uncertainty"] or r<c["minimum_property_reliability"]):
        return 1.
    q=c["qualification_probability"];effective=min(1,max(0,q+r*(p-q)))
    if effective>=q:return 1+c["qualified_bonus"]
    shortfall=min(1,max(0,(q-effective)/(q-c["probability_floor"])))
    return 1-c["maximum_property_penalty"]*shortfall**c["penalty_exponent"]


def check_forecast(seed):
    directory = PACKAGE/"04_runs"/"temporal"/f"seed_{seed}"
    results = []
    for year, filename in ((2019, "w4_developmental_dual_planner.jsonl"), (2024, "final_2024_planner.jsonl")):
        rows = [json.loads(line) for line in (directory/filename).read_text(encoding="utf-8-sig").splitlines() if line]
        weights = {(r["anchor_fusion_neural_weight"], r["anchor_fusion_component_weight"]) for r in rows}
        if len(weights)!=1:
            raise ValueError("Forecast blend differs between candidates")
        neural, prevalence = weights.pop()
        migration = percentiles({r["candidate_id"]:r["migration_score"] for r in rows})
        frequency = percentiles({r["candidate_id"]:sum(r["scalar_features"][:3]) for r in rows})
        scores = {n:neural*migration[n]+prevalence*frequency[n] for n in frequency}
        for r in rows:
            if not math.isclose(scores[r["candidate_id"]], r["forecast_score"], rel_tol=0, abs_tol=1e-12):
                raise ValueError("Forecast score differs from archived score")
        computed = sorted(scores, key=lambda n:(-scores[n],n))
        archived = [r["candidate_id"] for r in sorted(rows, key=lambda r:r["forecast_rank"])]
        if computed!=archived:
            raise ValueError("Forecast rank differs from archived rank")
        case = next(r for r in rows if r["names"]==["polymethylhydrosiloxane","imidazolium","tfsi"])
        results.append({"cutoff":year, "matched_forecast_ranks":len(rows), "neural_weight":neural,
                        "component_weight":prevalence, "case_forecast_rank":case["forecast_rank"],
                        "case_discovery_rank":case["discovery_rank"], "archive":str((directory/filename).relative_to(PACKAGE).as_posix())})
    return results


def check():
    published=json.loads((PACKAGE/"05_summary/selected3_summary_public.json").read_text(encoding="utf-8-sig"))
    tables=[];seeds=[];case_id=None
    for seed in (20260814,20260815,20260819):
        directory=PACKAGE/"04_runs/unified"/("seed_"+str(seed))
        rows=[json.loads(line) for line in (directory/"final_2024_unified.jsonl").read_text(encoding="utf-8-sig").splitlines() if line]
        settings=json.loads((directory/"seed_summary.json").read_text(encoding="utf-8-sig"))
        migration=percentiles({r["candidate_id"]:r["migration_score"] for r in rows})
        utility={};modifiers=[];case=None
        for r in rows:
            key=r["candidate_id"];c=r["planner_config"];w=c["migration_within_transfer_weight"];e=c["epsilon"]
            T=1/(w/max(e,migration[key])+(1-w)/max(e,r["application_novelty_score"]))
            floor=c["compatibility_floor"];compat=1-c["maximum_compatibility_penalty"]*max(0,floor-r["compatibility_score"])/floor
            uncert=1-c["maximum_uncertainty_penalty"]*r["migration_uncertainty"]
            phys=property_modifier(r);modifiers.append(phys);utility[key]=T*compat*uncert*phys
            if not math.isclose(utility[key],r["r42_utility"],rel_tol=0,abs_tol=1e-12):raise ValueError("Utility mismatch")
            if r["names"]==["polymethylhydrosiloxane","imidazolium","tfsi"]:
                case_id=key;case={"rank":r["r42_rank"],"T":T,"U":utility[key],"modifier":phys,
                     "threshold_probability":r["conductivity_threshold_probability"],
                     "reason":r["property_abstention_reasons"],"sigma_25C_S_cm":10**r["predicted_log10_s_cm"]}
        order=sorted(utility,key=lambda k:(-utility[k],k));saved=sorted(rows,key=lambda r:r["r42_rank"])
        if order!=[r["candidate_id"] for r in saved]:raise ValueError("Original seed rank mismatch")
        tables.append(percentiles(utility))
        seeds.append({"seed":seed,"matched_ranks":len(order),"forecast_panels":check_forecast(seed),"effective_qualified_bonus":settings["effective_planner_config"]["qualified_bonus"],
                  "high_confidence_platform_validated":settings["high_confidence_platform_validated"],
                  "candidate_ranks_changed_by_property":sum(r["discovery_rank"]!=r["r42_rank"] for r in rows),
                  "maximum_rank_displacement_by_property":max(abs(r["discovery_rank"]-r["r42_rank"]) for r in rows),
                  "range_of_actual_property_modifier":[min(modifiers),max(modifiers)],"PMHS_imidazolium_TFSI":case})
    consensus={n:statistics.fmean(t[n] for t in tables)-.25*statistics.pstdev(t[n] for t in tables) for n in tables[0]}
    order=sorted(consensus,key=lambda n:(-consensus[n],n))
    expected=sorted(published["all_seed_consensus"],key=lambda r:r["consensus_rank"])
    if order!=[r["candidate_id"] for r in expected]:raise ValueError("Published consensus ranks differ")
    result={"source":"local selected-three R4.1 forecast and R4.2 unified archived panels","seeds":seeds,"consensus_ranks_verified":len(order),
           "case_consensus_rank":order.index(case_id)+1,"case_consensus_score":consensus[case_id],
           "scope":"Final utility and order recomputed from archived upstream fields. No world-model retraining."}
    p=ROOT/"original_ranking_check.json"
    p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(sum(p["matched_forecast_ranks"] for s in seeds for p in s["forecast_panels"]),"forecast ranks,",
          sum(s["matched_ranks"] for s in seeds),"experimental-priority ranks and",len(order),"consensus ranks matched")


if __name__=="__main__":check()
