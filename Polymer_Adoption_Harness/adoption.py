"""The candidate-admission rule is distinct from the score and the later observed outcome."""
from collections import defaultdict
from math import exp, isfinite, log10, log1p
from physics import DEFAULT_THRESHOLD


def qualifies(row,cutoff,threshold):
    if not isfinite(threshold) or threshold<=0:raise ValueError("Conductivity threshold must be finite, in S/cm and positive")
    sigma=row.get("sigma_S_cm")
    temp=row.get("temperature_C")
    # The trial's two temperatures select what to simulate. Every valid returned condition can admit a candidate.
    return (row.get("status")=="predicted" and type(temp) in (int,float) and isfinite(temp) and temp>-273.15
            and row.get("unit","S/cm")=="S/cm"
            and type(row.get("source_year")) is int and 0<row["source_year"]<=cutoff and bool(row.get("source_doi"))
            and type(sigma) in (float,int) and isfinite(sigma) and sigma>=threshold)


def admit(paper_nominations,dated,cutoff,threshold=DEFAULT_THRESHOLD):
    if not isfinite(threshold) or threshold<=0:raise ValueError("Invalid HPG threshold")
    papers=set(paper_nominations);good=defaultdict(dict)
    # Scan every dated material, including materials absent from the controller nominations.
    for name,rows in dated.items():
        for r in rows:
            if r["material"]!=name:raise ValueError("Recipe/material mismatch")
            if qualifies(r,cutoff,threshold):
                if r["recipe"] in good[name] and good[name][r["recipe"]]!=r:raise ValueError("Conflicting recipe")
                good[name][r["recipe"]]=r
    pool={}
    for name in sorted(papers|set(good)):
        recipes=list(good.get(name,{}).values())
        pool[name]={"paper":name in papers,"hpg":bool(recipes),"route":"both" if recipes and name in papers
                    else "hpg_only" if recipes else "paper_only","qualifying_recipes":sorted(recipes,key=lambda x:x["recipe"]),
                    "temperatures_C":sorted({r["temperature_C"] for r in recipes})}
    return pool


def ranked(panel,paper,physical,dated,known,policy,year,threshold):
    from graph import features
    if set(panel)!=set(paper) or set(physical)!=set(dated) or not set(dated)<=set(panel):
        raise ValueError("Incomplete controller coverage")
    if policy["through"]>year:raise ValueError("Future learning state")
    pool=admit([k for k,r in paper.items() if r["vote"]>0],dated,year,threshold)
    result={}
    for name,p in panel.items():
        judgment=paper[name];v=judgment["vote"];x=features(p,year,v)
        base=0.30*log1p(p["papers"])+0.25*x[1]
        learned=sum(w*t for w,t in zip(policy["weights"],x,strict=True))
        text_score=base+0.40*v+learned
        gate=pool.get(name,{"route":"outside","qualifying_recipes":[],"temperatures_C":[]})
        hits=gate["qualifying_recipes"]
        bonus=min(0.80,0.45+0.20*max(0,log10(max(r["sigma_S_cm"] for r in hits)/threshold))) if hits else 0.
        second=physical.get(name,{})
        # Only a supported physical interpretation can alter ranking. Admission is unconditional on it.
        score=text_score+bonus+(0.12*second.get("vote",0) if hits else 0.)
        result[name]={"source_count":p["papers"],"latest_source":p["latest"],"paper_vote":v,
          "paper_judgment":judgment,"physical_judgment":second,"base_score":base,"text_score":text_score,
          "score":score,"features":x,"hpg_evaluated":name in dated,"hpg_bonus":bonus,
          "in_pool":name in pool,"route":gate["route"],"temperatures_C":gate["temperatures_C"],
          "qualifying_recipes":hits,"stratum":"repeat" if known.get(name) else "first_observed",
          "past_spe_dois":sorted({r["doi"] for r in known.get(name,[])}),
          "forecast_horizon":[year+1,year+5],"role":second.get("role") or judgment["role"]}
    for column,subset,rank in (("text_score",result,"text_rank"),("score",result,"rank"),
              ("score",[n for n in result if n in pool],"pool_rank")):
        for i,k in enumerate(sorted(subset,key=lambda n:(-result[n][column],n)),1):result[k][rank]=i
    if not all(result[k]["in_pool"] for k,rr in dated.items() if any(qualifies(r,year,threshold) for r in rr)):
        raise AssertionError("A qualified material was omitted")
    return result


def seed(cutoff):
    return {"through":cutoff,"weights":[0.]*10,"memory":[]}


def learn(frozen,events,policy,cutoff):
    rows=frozen["rankings"];weights=policy["weights"].copy();pairs=[]
    positives={k for k,r in rows.items() if k in events and r["stratum"]=="first_observed"}
    controls={k for k,r in rows.items() if k not in events and r["stratum"]=="first_observed"}
    for k in sorted(positives):
        p=rows[k]
        eligible=[n for n in controls if rows[n]["rank"]<p["rank"]]
        # Match four higher-ranked, unobserved controls by document exposure and recency.
        near=sorted(eligible,key=lambda n:(abs(rows[n]["features"][0]-p["features"][0]),
               abs(rows[n]["features"][1]-p["features"][1]),p["rank"]-rows[n]["rank"],n))[:4]
        for n in near:
            q=rows[n];dx=[a-b for a,b in zip(p["features"],q["features"])]
            old_dx=[(a if p["paper_vote"] else 0)-(b if q["paper_vote"] else 0)
                    for a,b in zip(p["features"],q["features"])]
            pairs.append({"observed":k,"unobserved":n,"positive_rank":p["rank"],"other_rank":q["rank"],
                          "dx":dx,"previous_zero":not any(old_dx),"both_abstained":not(p["paper_vote"] or q["paper_vote"])})
    if pairs:
        for _ in range(5):
            grad=[0.]*len(weights)
            for pair in pairs:
                dx=pair["dx"];margin=sum(w*d for w,d in zip(weights,dx))
                response=1/(1+exp(max(-30,min(30,margin))))
                grad=[g+response*d for g,d in zip(grad,dx)]
            weights=[max(-1.2,min(1.2,w+0.4*(g/len(pairs)-0.08*w))) for w,g in zip(weights,grad)]
    misses=sorted(positives,key=lambda k:-rows[k]["rank"])
    memory={"reveal_through":cutoff,"first_observed":len(positives),"pool_hits":sum(rows[k]["in_pool"] for k in positives),
            "outside_pool_observed":sum(not rows[k]["in_pool"] for k in positives),
            "missed_roles":sorted({e["role"] for k in positives if not rows[k]["in_pool"] for e in events[k]}),
            "missed_cues":sorted({i for k in misses[:5] for i,val in enumerate(rows[k]["features"][2:9]) if val})}
    return {"through":cutoff,"weights":weights,"memory":(policy["memory"]+[memory])[-4:]},pairs
