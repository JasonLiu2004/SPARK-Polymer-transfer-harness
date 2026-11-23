"""Build material–publication–specimen–role edges only from independently read, dated papers."""
from collections import defaultdict
import math
import re
from structures import identity

AXES=("backbone","organic_cation","anion")
CUES={
    "coordination":r"coordinat|complexat|solvat|chelati|ion.binding|ether oxygen",
    "mobility":r"segmental|amorphous|glass.transition|free.volume|chain.mobility|crystalli",
    "membrane":r"membrane|free.standing|thin.film|scaffold|separator",
    "mechanics":r"toughness|tensile|elastic|cross.link|self.heal|mechanical",
}
NON_SPECIFIC={"polymer","polymers","copolymer","copolymers","polymer electrolyte","polymer electrolytes",
              "solid polymer electrolyte","polymer membrane","polymer membranes","polymer matrix"}


def evidence_rows(record):
    view=record["segments"]
    for m in record["materials"]:
        name=identity(m["name"],view)
        if not name or name in NON_SPECIFIC or name.startswith("unresolved abbreviation "):
            continue
        # A quoted acronym with no trusted expansion cannot identify a future material.
        if name==m["name"].strip().casefold() and re.fullmatch(r"[A-Z][A-Z0-9-]{1,7}",m["name"].strip()):
            continue
        yield name,{"doi":record["doi"],"year":record["year"],"name":m["name"],"sample":m["sample"],
              "role":m["role"],"stage":record["stage"],"identity_quote":view[m["name_ref"]],
              "quote":view[m["evidence_ref"]],"source_locator":[m["name_ref"],m["evidence_ref"]],
              "axes":{k:m[k] for k in AXES if m[k]}}


def build(records,cutoff):
    nodes=defaultdict(list)
    ledger={}
    for doi,r in sorted(records.items()):
        if r["year"]>cutoff:raise ValueError("Future publication in knowledge graph")
        edges=list(evidence_rows(r))
        ledger[doi]={"year":r["year"],"stage":r["stage"],"items":[{"material":name,**ev} for name,ev in edges]}
        if r["stage"]=="general_polymer":
            for name,ev in edges:nodes[name].append(ev)
    panel={}
    for name,items in sorted(nodes.items()):
        sources=sorted(items,key=lambda r:(-r["year"],r["doi"],r["name"],r["role"]))
        dois={s["doi"] for s in sources}
        text=" ".join(s["quote"] for s in sources)
        panel[name]={"sources":sources,"papers":len(dois),"latest":sources[0]["year"],
                     "cues":{k:int(bool(re.search(pat,text,re.I))) for k,pat in CUES.items()},
                     "axes":{k:sorted({s["axes"][k] for s in sources if k in s["axes"]}) for k in AXES}}
    return ledger,panel


def observations(records,cutoff,exclude=()):
    events=defaultdict(list)
    for doi,r in sorted(records.items()):
        if r["year"]>cutoff:raise ValueError("Future publication in outcome collection")
        if doi in exclude or r["stage"] not in {"solid_sample","solid_device"}:continue
        for name,e in evidence_rows(r):
            if e["role"] not in {"host","cohost","reinforcement","interface","crosslinker","filler","binder","membrane"}:continue
            events[name].append({**e,"solid_quote":r["segments"][r["solid_ref"]],
                "device_quote":r["segments"].get(r["device_ref"],"")})
    return dict(events)


def features(material,cutoff,vote):
    # A zero vote means the controller abstained. The graph features still exist.
    return [min(1,math.log1p(material["papers"])/4), math.exp(-(cutoff-material["latest"])/8),
            *[float(material["cues"][k]) for k in CUES],
            *[float(bool(material["axes"][k])) for k in AXES],float(vote)/2]
