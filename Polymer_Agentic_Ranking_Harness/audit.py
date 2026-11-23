"""Independently replay the logged native tool answers and reconstruct every frozen ordinal tier offline."""
import argparse
import json
from datetime import datetime
from evidence import (ROOT,SOURCE,DATA,YEARS,INTERVALS,Evidence,admit,merge_interval,observations,
                      file_hash,fingerprint,packed,read_json,verified,write_json)
from agent import FINAL,OBJECTIVE,ToolSession,decode_arguments
from ordinal import positions
from ranking_policy import DEFAULT_RUN, EXPOSURE, ORDINAL, apply_exposure_policy, implementation_path, registered_policy


def require(condition,message):
    if not condition:raise ValueError(message)


def time_of(d):
    return datetime.fromisoformat(d["sealed_at"])


class Decisions:
    def __init__(self,home,view,memory,protocol):
        self.section=home/str(view.year)
        self.provider=home.parent/"provider"
        self.view,self.memory,self.protocol=view,memory,protocol
        self.visited={};self.requests=set();self.actions={}

    def get(self,mode,key,cases=None):
        if key in self.visited:return self.visited[key]
        d=verified(self.section/"decisions"/mode/(key+".json"))
        require(d["contract"]==key and d["year"]==self.view.year and d["mode"]==mode,"Wrong decision file")
        checked=None;sess=None;first=None;returned=[]
        for receipt in d["receipts"]:
            response=verified(self.provider/(receipt+".response.json"))
            req=read_json(self.provider/(receipt+".request.json"));self.requests.add(receipt)
            require(fingerprint(req)==response["request"]==receipt and response["provider_id"] and
                    response["http_status"]==200 and req["model"]==response["model"]==self.protocol["model"],"Invalid provider receipt")
            if "endpoint" in self.protocol:
                require(response.get("endpoint")==self.protocol["endpoint"] and
                        response.get("returned_model")==self.protocol["returned_model"],"Provider deployment mismatch")
            require(req["messages"][0]=={"role":"system","content":OBJECTIVE},"Unexpected system message")
            header=json.loads(req["messages"][1]["content"])
            if sess is None:
                first=header
                require(d["mapping"]==header.get("candidates",header.get("closed_cases")),"Candidate presentation mismatch")
                require(header.get("cutoff",header.get("forecast_cutoff"))==self.view.year,"Cutoff mismatch")
                require(header.get("memory",header.get("previous_memory"))==self.memory,"Memory outside its frozen date")
                sess=ToolSession(mode,self.view,list(d["mapping"].values()),self.memory,"audit",cases=cases)
                sess.mapping=d["mapping"]
                inv={n:c for c,n in sess.mapping.items()}
                sess.landmarks=[inv[n] for n in d["landmarks"]];sess.challengers=set(sess.mapping)-set(sess.landmarks)
            require(header==first,"Conversation substituted another candidate panel")
            actual=[(m["tool_call_id"],m["content"]) for m in req["messages"] if m["role"]=="tool"]
            require(actual==returned,"Evidence sent to the provider differs from the dated tools")
            offered={t["function"]["name"] for t in req["tools"]}
            for call in response["message"].get("tool_calls") or []:
                op=call["function"]["name"]
                try:
                    args=decode_arguments(call["function"]["arguments"])
                    if op not in offered:raise ValueError("Choose a currently offered tool")
                    if op==FINAL[mode]["function"]["name"]:
                        checked=sess.submit(args)
                        answer={"accepted":True}
                    else:
                        answer={"evidence":sess.lookup(op,args),"next_required":sess.missing() or FINAL[mode]["function"]["name"]}
                except (KeyError,TypeError,ValueError,AttributeError) as exc:
                    answer={"correction":str(exc)}
                returned.append((call["id"],packed(answer)))
        require(sess is not None and sess.actions==d["actions"],"Tool trace not reproduced")
        if "subdecisions" not in d:
            require(checked is not None and checked==d["result"],"Submitted provider judgement differs from frozen result")
        else:
            subs=[self.get(v["mode"],v["contract"],cases) for v in d["subdecisions"]]
            if mode in ("place","nominate"):
                field="placements" if mode=="place" else "nominations"
                rebuilt={n:v for child in subs for n,v in child["result"][field].items()}
                require(rebuilt==d["result"][field],"Failed to reproduce decomposed decisions")
            else:
                place=subs[0];pivot=place["landmarks"][0];slots=place["result"]["placements"]
                tiers=[];rest=iter(subs[1:])
                for slot in ("S1","E1","TAIL"):
                    members={n for n,s in slots.items() if s==slot}
                    if slot=="E1":members.add(pivot)
                    if slot=="E1" or len(members)<=1:
                        if members:tiers.append(members)
                    else:
                        child=next(rest);require(set(child["mapping"].values())==members,"Repair changed a comparison panel")
                        tiers.extend(map(set,child["result"]["tiers"]))
                require(tiers==list(map(set,d["result"]["tiers"])),"Ordinal repair differs from provider evidence")
        for step in d["actions"]:
            label=step["tool"];self.actions[label]=self.actions.get(label,0)+1
        self.visited[key]=d
        return d


def reproduce_tree(index,nodes,path,members):
    node=nodes[path]
    if "direct" in node:
        if node["direct"]:
            d=index.get("order",node["direct"][0])
            require(set(d["mapping"].values())==members,"Leaf membership mismatch")
            tiers=d["result"]["tiers"]
        else:
            require(len(members)==1,"Unevaluated nonsingleton")
            tiers=[list(members)]
        require(tiers==node["tiers"],"Stored leaf differs from model")
        return tiers
    d=index.get("order",node["landmark_decision"])
    tiers=d["result"]["tiers"];reps=[t[0] for t in tiers];slots={}
    for key in node["placements"]:
        judge=index.get("place",key)
        require(judge["landmarks"]==reps,"Changed bridge landmarks")
        incoming=judge["result"]["placements"]
        require(not slots.keys()&incoming.keys(),"Duplicate challenger")
        slots.update(incoming)
    pivots={n for t in tiers for n in t}
    require(not pivots&slots.keys() and pivots|slots.keys()==members,"Incomplete split")
    result=[];segments=[]
    for i in range(len(tiers)+1):
        gap="S"+str(i+1) if i<len(tiers) else "TAIL"
        names={n for n,s in slots.items() if s==gap}
        if names:
            child=path+"/"+gap;segments.append({"child":child})
            result.extend(reproduce_tree(index,nodes,child,names))
        if i<len(tiers):
            tied=sorted(tiers[i]+[n for n,s in slots.items() if s=="E"+str(i+1)])
            result.append(tied);segments.append({"tie":tied})
    require(segments==node["segments"],"Stored interleaving differs from provider comparisons")
    return result


def audit(home,save=True,available=False):
    protocol=verified(home/"protocol.json")
    policy=registered_policy(protocol)
    for name,sha in protocol["own_code"].items():
        require(file_hash(implementation_path(name,policy))==sha,"Source changed: "+name)
    for name,sha in protocol["upstream_code"].items():
        require(file_hash(SOURCE/name)==sha,"Source changed: "+name)
    grid=verified(DATA/"physics/grid.json")
    require(grid["sha256"]==protocol["hpg_grid"],"Different HPG inference")
    broad={};past={};memory=[];prior=None;last_reveal=None;requests=set();totals={}
    stats=[];freezes=[];revealed=[]
    def interval(stream,lo,hi):return verified(DATA/"intervals"/stream/f"{lo}_{hi}.json")
    merge_interval(past,interval("spe",*INTERVALS[0]))
    for lo,y in INTERVALS:
        if not (home/str(y)/"forecast.json").exists():
            if not available:
                raise ValueError(f"{y} has no sealed forecast. Use audit.py --available to verify the completed prefix.")
            require(not any((home/str(later)/"forecast.json").exists() for later in YEARS if later>y),
                    "A later window was sealed before an earlier forecast")
            require(not (home/str(y)/"reveal.json").exists(),"Outcome present without a sealed forecast")
            break
        source=interval("broad",lo,y);merge_interval(broad,source)
        view=Evidence(y,broad,past,grid,protocol["threshold_S_cm"])
        g=verified(home/str(y)/"graph.json");f=verified(home/str(y)/"forecast.json")
        freezes.append(f["sha256"])
        require(g["digest"]==view.digest and g["previous"]==prior and g["new_input"]==source["sha256"] and
                g["publications"]==view.ledger and g["known_SPE"]==view.known,"As-of graph mismatch")
        prior=g["sha256"];require(f["protocol"]==protocol["sha256"] and f["graph"]==prior and f["memory"]==memory,"Wrong prediction state")
        require(last_reveal is None or time_of(last_reveal)<=time_of(f),"Learning out of time order")
        tree=verified(home/str(y)/"comparisons.json")
        require(tree["sha256"]==f["comparison_tree"] and time_of(tree)<=time_of(f) and time_of(g)<=time_of(f),"Wrong comparison tree or freeze time")
        index=Decisions(home,view,memory,protocol);nominated={};scanned=set()
        for key in tree["intake"]:
            d=index.get("nominate",key);group=set(d["mapping"].values())
            require(not group&scanned,"Duplicate intake observations")
            scanned.update(group);nominated.update(d["result"]["nominations"])
        require(scanned==view.panel.keys(),"Screen skipped materials")
        pool=admit(nominated,view.physical,y,view.threshold)
        preferences=reproduce_tree(index,tree["nodes"],"root",set(view.panel)) if view.panel else []
        require(preferences==tree["tiers"] and f["rows"].keys()==view.panel.keys(),"LLM comparison or panel differs")
        require(f.get("primary_ranking",ORDINAL)==policy,"Forecast method differs from registration")
        tiers=apply_exposure_policy(view.panel,preferences,y) if policy==EXPOSURE else preferences
        require(tiers==f["tiers"],"Primary ordering differs from the registered rule and dated evidence")
        raw=positions(preferences)
        ranks=positions(tiers);within=positions(tiers,pool)
        for n,r in f["rows"].items():
            require(ranks[n]==(r["rank_min"],r["rank_max"]) and (list(within[n]) if n in within else None)==r["pool_rank"],"Wrong rank interval")
            require((r["source_count"],r["latest_source"])==(view.panel[n]["papers"],view.panel[n]["latest"]),"Wrong publication coverage")
            require(r["stratum"]==("repeat" if view.known.get(n) else "first_observed") and
                    r["route"]==pool.get(n,{}).get("route","outside"),"Wrong stratum or admission basis")
            if policy==EXPOSURE:
                require(raw[n]==(r["llm_rank_min"],r["llm_rank_max"]),"Wrong unconstrained LLM preference interval")
            require(r["in_pool"]==(n in pool) and r["qualifying_recipes"]==pool.get(n,{}).get("qualifying_recipes",[])
                    and r["paper_nomination"]==nominated.get(n),"Admission differs")
        has_feedback=(home/str(y)/"reveal.json").exists()
        if y<YEARS[-1] and (has_feedback or not available):
            target=interval("spe",y+1,y+5);rev=verified(home/str(y)/"reveal.json")
            require(rev["forecast"]==f["sha256"] and rev["spe_input"]==target["sha256"] and time_of(f)<=time_of(rev),"Outcome binding/timing mismatch")
            from memory import closed_cases
            events=observations(target["records"],y+5)
            cases,counts=closed_cases(f,events,view)
            require(events==rev["events"] and cases==rev["training_cases"] and counts==rev["memory"]["counts"],"Incorrect feedback sample")
            d=index.get("reflect",rev["decision"],cases)
            require(d["result"]["lessons"]==rev["memory"]["lessons"] and rev["memory"]["through"]==y+5,"Unsupported memory")
            memory=memory+[rev["memory"]];merge_interval(past,target);last_reveal=rev
            revealed.append(y)
        elif y==YEARS[-1]:
            require(not has_feedback,"Unexpected open-window labels")
        else:
            require(not any((home/str(later)/"forecast.json").exists() for later in YEARS if later>y),
                    "Next forecast exists before the preceding feedback")
        requests.update(index.requests)
        for k,v in index.actions.items():totals[k]=totals.get(k,0)+v
        stats.append({"year":y,"materials":len(ranks),"tiers":len(tiers),"admitted":len(pool),"high_admitted":len(view.high),
                      "decisions":len(index.visited),"requests":len(index.requests)})
        if policy==EXPOSURE:
            stats[-1].update(llm_tiers=len(preferences),changed_from_llm=sum(ranks[n]!=raw[n] for n in ranks))
        if available or policy==EXPOSURE:
            stats[-1]["forecast_sha256"]=f["sha256"]
    if not available:
        end=verified(home/str(YEARS[-1])/"forecast.json");excluded=set(broad)|set(past);earlier=set()
        for first,year in INTERVALS:
            b=verified(home/"verification"/f"{year}.json")
            source=interval("independent",first,year)
            unique={doi:r for doi,r in source["records"].items() if doi not in excluded}
            events=observations(unique,year)
            require(time_of(b)>=time_of(end) and b["forecasts"]==freezes and b["input"]==source["sha256"] and
                    b["disjoint_papers"]==len(unique) and b["events"]==events and b["earlier"]==sorted(earlier),
                    "Independent outcome input, timing, panel binding or evidence mismatch")
            earlier.update(events)
    out={"verified_windows":stats,"unique_provider_responses":len(requests),"verified_tool_calls":totals,
         "material_window_rows":sum(s["materials"] for s in stats),"high_material_windows_admitted":sum(s["high_admitted"] for s in stats)}
    if policy==EXPOSURE:
        start=time_of(protocol)
        reused=sum(time_of(verified(home.parent/"provider"/(key+".response.json")))<start for key in requests)
        out.update(primary_ranking=policy,provider_receipts_predating_protocol=reused,
                   provider_receipts_since_protocol=len(requests)-reused)
    supplement=home/"exposure_order"
    if not available and (supplement/"protocol.json").exists():
        from evidence_order import constrained_tiers
        method=verified(supplement/"protocol.json")
        require(method["parent"]==protocol["sha256"] and method["code_sha256"]==file_hash(ROOT/"evidence_order.py"),
                "Changed exploratory protocol")
        verified_rows=0
        for year in YEARS:
            f=verified(home/str(year)/"forecast.json")
            s=verified(supplement/f"{year}.json")
            require(s["parent_forecast"]==f["sha256"] and s["method"]==method["sha256"] and
                    s["tiers"]==constrained_tiers(f["rows"]) and s["neutral_fronts"]==constrained_tiers(f["rows"],False),
                    "Exploratory order differs from published evidence and provider ranks")
            verified_rows+=len(f["rows"])
        out["exploratory_ranks_reconstructed"]=verified_rows
    progress_fields={"scope":"sealed_forecasts_and_revealed_primary_outcomes","planned_cutoffs":list(YEARS),
                     "sealed_cutoffs":[s["year"] for s in stats],"revealed_cutoffs":revealed}
    if available:
        out.update(progress_fields)
    if save and available:
        from progress import export_available
        export_available(home,out)
    elif save:
        write_json(home/"results"/"audit.json",out)
        if policy==EXPOSURE:
            from progress import export_available
            export_available(home,{**out,**progress_fields})
    print("Audited",out["material_window_rows"],"material-window rankings,",len(requests),"provider responses",flush=True)
    return out


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--run-id",default=DEFAULT_RUN)
    p.add_argument("--check-only",action="store_true",help="Verify the run without updating its audit report")
    p.add_argument("--available",action="store_true",help="Verify and export only the sealed windows, without opening the independent retrieval")
    args=p.parse_args()
    audit(ROOT/"runs"/args.run_id,save=not args.check_only,available=args.available)
