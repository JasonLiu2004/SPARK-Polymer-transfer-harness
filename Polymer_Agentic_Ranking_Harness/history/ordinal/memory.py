"""Construct the agent's feedback from a sealed forecast and that window's subsequent SPE uses."""
from collections import Counter
from evidence import excerpt


def closed_cases(forecast,events,view):
    rows=forecast["rows"]
    at_risk={n for n,r in rows.items() if r["stratum"]=="first_observed"}
    hits=at_risk & events.keys()
    # The ledgers and metrics retain every observation. Show every positive to the agent,
    # accompanied by high-ranked unobserved alternatives with comparable publication exposure.
    negatives=at_risk-hits
    contrasts=set()
    for n in sorted(hits,key=lambda k:(-rows[k]["rank_min"],k)):
        possible=negatives-contrasts
        if not possible:break
        ahead=[k for k in possible if rows[k]["rank_min"]<rows[n]["rank_min"]]
        other=min(ahead or possible,key=lambda k:(abs(rows[k]["source_count"]-rows[n]["source_count"]),rows[k]["rank_min"],k))
        contrasts.add(other)
    cases={}
    for n in sorted(hits|contrasts):
        future=sorted(events.get(n,[]),key=lambda e:(e["year"],e["doi"]))
        src=view.publications(n)["sample_evidence"][0]
        r=rows[n]
        cases[n]={"frozen_rank_range":[r["rank_min"],r["rank_max"]],"universe":len(rows),
                  "frozen_route":r["route"],"source":src,
                  "post_reveal_status":"observed SPE application" if n in hits else "unobserved in this retrieval",
                  "next_window_specimen":excerpt(future[0]) if future else None,
                  "dois":[src["doi"]]+([future[0]["doi"]] if future else [])}
    return cases,{"eligible":len(at_risk),"observed":len(hits),"pool_hits":sum(rows[n]["in_pool"] for n in hits),
                  "unobserved_comparators":len(contrasts),"observed_roles":dict(Counter(e["role"] for n in hits for e in events[n]))}


def reflect(agent,forecast,events):
    cases,counts=closed_cases(forecast,events,agent.view)
    decision=agent.decide("reflect",list(cases),["after_freeze",forecast["cutoff"]],cases=cases)
    lessons=decision["result"]["lessons"]
    if not counts["observed"] and lessons:raise ValueError("Qualitative lessons require observed adoption evidence")
    return {"through":agent.view.year+5,"counts":counts,"lessons":lessons},decision["contract"],cases
