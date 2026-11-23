"""Whole-panel ordinal ranking. Only the material comparisons returned by the agent establish priorities."""
from concurrent.futures import ThreadPoolExecutor
from evidence import spread

LEAF = 20
LANDMARKS = 5
CHUNK = 16


def chunks(names, size):
    return [names[i:i+size] for i in range(0,len(names),size)]


def run_jobs(pool, fn, jobs):
    return dict(zip(jobs,pool.map(fn,jobs.values()),strict=True))


def screen(agent, names, workers):
    ordered=spread(names,[agent.view.year,"intake"])
    groups=chunks(ordered,18)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        decisions=list(pool.map(lambda group:agent.decide("nominate",group,"intake"),groups))
    nominated={};covered=set()
    for d in decisions:
        subset=set(d["mapping"].values())
        if covered & subset:raise ValueError("Repeated intake candidate")
        covered.update(subset)
        nominated.update(d["result"]["nominations"])
    if covered!=set(names):raise ValueError("Incomplete literature intake")
    return nominated,[d["contract"] for d in decisions]


def rank_all(agent,names,workers,leaf=LEAF,landmarks=LANDMARKS,chunk=CHUNK):
    if not names:return [],{}
    if not 1<=landmarks<leaf or chunk<1:raise ValueError("Invalid ordinal scheduling sizes")
    if len(names)!=len(set(names)):raise ValueError("Duplicate candidate in universe")
    current={"root":list(names)};nodes={}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while current:
            direct={};pivot={};following={}
            for path,group in current.items():
                if len(group)==1:
                    nodes[path]={"tiers":[group],"direct":[]}
                elif len(group)<=leaf:
                    direct[path]=(group,[path,"leaf"])
                else:
                    pick=spread(group,[agent.view.year,path,"landmarks"])[:landmarks]
                    pivot[path]=(pick,[path,"landmarks"])
            ordered=run_jobs(pool,lambda job:agent.decide("order",*job),{**direct,**pivot})
            place_jobs={};plans={}
            for path,d in ordered.items():
                tiers=d["result"]["tiers"]
                if path in direct:
                    nodes[path]={"tiers":tiers,"direct":[d["contract"]]}
                    continue
                representatives=[t[0] for t in tiers]
                selected={k for t in tiers for k in t}
                others=spread(set(current[path])-selected,[agent.view.year,path,"challengers"])
                plans[path]=(tiers,d["contract"],len(others))
                for i,group in enumerate(chunks(others,chunk)):
                    place_jobs[(path,i)]=(group+representatives,[path,"locate",i],representatives)
            placements=run_jobs(pool,lambda job:agent.decide("place",job[0],job[1],landmarks=job[2]),place_jobs)
            for path,(anchors,anchor_decision,n_other) in plans.items():
                bands={};traces=[];assigned=set()
                for j in range((n_other+chunk-1)//chunk):
                    d=placements[path,j];traces.append(d["contract"])
                    for name,slot in d["result"]["placements"].items():
                        if name in assigned:raise ValueError("Overlapping comparison groups")
                        assigned.add(name);bands.setdefault(slot,[]).append(name)
                if assigned!={n for n in current[path] if all(n not in t for t in anchors)}:
                    raise ValueError("Placement lost a material")
                segments=[]
                for i in range(len(anchors)+1):
                    gap="S"+str(i+1) if i<len(anchors) else "TAIL"
                    if bands.get(gap):
                        child=path+"/"+gap; following[child]=bands[gap]
                        segments.append({"child":child})
                    if i<len(anchors):
                        segments.append({"tie":sorted(anchors[i]+bands.get("E"+str(i+1),[]))})
                nodes[path]={"segments":segments,"landmark_decision":anchor_decision,"placements":traces}
            current=following
    def flatten(path):
        node=nodes[path]
        if "tiers" in node:return node["tiers"]
        tiers=[]
        for s in node["segments"]:
            tiers.extend([s["tie"]] if "tie" in s else flatten(s["child"]))
        return tiers
    tiers=flatten("root");flat=[n for t in tiers for n in t]
    if len(flat)!=len(names) or set(flat)!=set(names) or any(not t for t in tiers):
        raise ValueError("Ordinal tree produced an invalid partition")
    return tiers,nodes


def positions(tiers,select=None):
    result={};lo=1
    for tier in tiers:
        group=[n for n in tier if select is None or n in select]
        hi=lo+len(group)-1
        for n in group:result[n]=(lo,hi)
        lo=hi+1
    return result
