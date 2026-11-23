"""Explore an exposure-constrained ordering using the sealed, native LLM comparisons."""
import argparse
from collections import defaultdict
from evidence import ROOT, YEARS, file_hash, seal, verified
from ordinal import positions


def constrained_tiers(rows, use_agent=True):
    """Select the agent's highest available tier in a partial order of publication exposure.

    A point dominates another when both date and DOI count are at least as large
    and at least one is strictly larger. Equal-exposure materials never block
    one another. Grouping by their identical coordinates avoids per-material edges.
    """
    groups = defaultdict(set)
    for name,row in rows.items():
        groups[(row["source_count"], row["latest_source"])].add(name)
    blocks = {}
    dependents = defaultdict(list)
    for point in groups:
        parents = [other for other in groups if other!=point and other[0]>=point[0] and other[1]>=point[1]]
        blocks[point] = len(parents)
        for other in parents:
            dependents[other].append(point)
    available = {point for point in groups if blocks[point]==0}
    result = []
    while available:
        options = [(point,name) for point in available for name in groups[point]]
        if use_agent:
            best = min(rows[name]["rank_min"] for _,name in options)
            options = [(point,name) for point,name in options if rows[name]["rank_min"]==best]
        result.append(sorted(name for _,name in options))
        emptied = set()
        for point,name in options:
            groups[point].remove(name)
            if not groups[point]:
                emptied.add(point)
        available.difference_update(emptied)
        for point in emptied:
            for other in dependents[point]:
                blocks[other] -= 1
                if blocks[other]==0:
                    available.add(other)
    if sum(map(len,result))!=len(rows):
        raise ValueError("The exposure constraint failed to rank every material")
    return result


def register(home):
    return seal(home/"exposure_order"/"protocol.json",{
        "parent":verified(home/"protocol.json")["sha256"],
        "code_sha256":file_hash(ROOT/"evidence_order.py"),
        "status":"exploratory secondary analysis devised after looking at historical primary retrieval results",
        "features":["distinct pre-cutoff DOI count", "latest pre-cutoff source year"],
        "ordering":"subject to two-axis dominance, take the highest still-eligible tier of the sealed agent order",
        "controls":"neutral nondominated fronts; fully autonomous agent; frequency/recency; previous method",
        "pool":"exact projection of the parent's adopted union including all qualifying HPG materials",
        "validation":"same named first-use candidates and retrospective SPE outcomes; 2024 remains prospective",
        "provider":"reuses real signed ordinal judgements; no separate model call or fitted parameters"})


def run(home):
    from evaluate import metrics,write_table
    protocol=register(home)
    forecasts = {y:verified(home/str(y)/"forecast.json") for y in YEARS}
    ranks=[];measure=[]
    for year,f in forecasts.items():
        rows=f["rows"]
        agent_tiers=constrained_tiers(rows)
        neutral_tiers=constrained_tiers(rows,use_agent=False)
        state=seal(home/"exposure_order"/f"{year}.json",{
            "parent_forecast":f["sha256"],"method":protocol["sha256"],"cutoff":year,
            "tiers":agent_tiers,"neutral_fronts":neutral_tiers})
        if len(state["tiers"])!=len(agent_tiers):
            raise ValueError("Inconsistent exposure projection")
        pool={n for n,r in rows.items() if r["in_pool"]}
        current=positions(agent_tiers);in_pool=positions(agent_tiers,pool);control=positions(neutral_tiers)
        new={n for n,r in rows.items() if r["stratum"]=="first_observed"}
        new_pool=positions(agent_tiers,new & pool)
        for tier in agent_tiers:
            for n in tier:
                lo,hi=in_pool.get(n,(None,None));first_lo,first_hi=new_pool.get(n,(None,None))
                ranks.append({"cutoff":year,"material":n,"rank_min":current[n][0],"rank_max":current[n][1],
                              "in_pool":n in pool,"pool_rank_min":lo,"pool_rank_max":hi,"stratum":rows[n]["stratum"],
                              "first_use_pool_rank_min":first_lo,"first_use_pool_rank_max":first_hi,
                              "unconstrained_rank_min":rows[n]["rank_min"],"unconstrained_rank_max":rows[n]["rank_max"],
                              "prior_DOI_count":rows[n]["source_count"],"latest_source":rows[n]["latest_source"],
                              "route":rows[n]["route"],"qualifying_HPG_recipes":len(rows[n]["qualifying_recipes"])})
        if year==YEARS[-1]:
            continue
        primary=verified(home/str(year)/"reveal.json")
        independent=verified(home/"verification"/f"{year+5}.json")
        for source,events,prior in (("primary",primary["events"],()),("disjoint",independent["events"],independent["earlier"])):
            cohort=new-set(prior)
            for method,order in (("exposure_agent",current),("exposure_fronts",control)):
                score={n:-order[n][0] for n in cohort}
                measure.append({"cutoff":year,"source":source,"method":method,**metrics(score,events)})
    out=home/"results"
    write_table(out/"exposure_order.csv",ranks)
    write_table(out/"exposure_order_metrics.csv",measure)
    write_table(out/"2024_exposure_first_adoption.csv",[r for r in ranks if r["cutoff"]==2024 and r["first_use_pool_rank_min"] is not None],
                list(ranks[0]) if ranks else ())


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="ordinal")
    parser.add_argument("--register", action="store_true")
    args=parser.parse_args()
    home=ROOT/"runs"/args.run_id
    if args.register:
        print(register(home)["sha256"])
    else:
        run(home)
