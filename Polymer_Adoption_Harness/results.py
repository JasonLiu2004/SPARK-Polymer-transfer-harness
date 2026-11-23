"""Export material, recipe and observation tables and report independently checkable counts."""
import csv
import json
from collections import Counter
from itertools import groupby
import math
from common import DATA,ROOT,RUN,YEARS,verified,write_json
from physics import PUBLIC,dated_predictions
from adoption import admit,qualifies
from graph import build


def average_precision(rows,positives,score):
    names=sorted(rows,key=lambda k:-rows[k][score])
    total=len(set(names)&positives)
    if not total:return None
    hits=seen=0;area=0.
    for _,block in groupby(names,key=lambda k:rows[k][score]):
        group=list(block);m=len(group);c=sum(k in positives for k in group)
        if c:
            for j in range(1,m+1):
                prev=(j-1)*(c-1)/(m-1) if m>1 else 0.
                area+=(c/m)*(hits+1+prev)/(seen+j)
        hits+=c;seen+=m
    return area/total


def top_recall(rows,positives,score,fraction=0.20):
    if not positives:return None
    names=sorted(rows,key=lambda k:-rows[k][score]);limit=math.ceil(len(names)*fraction);hits=0.;seen=0
    for _,block in groupby(names,key=lambda k:rows[k][score]):
        group=list(block);take=min(limit-seen,len(group))
        if take<=0:break
        hits+=sum(k in positives for k in group)*take/len(group);seen+=take
    return hits/len(positives)


def table(path,rows,fields):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8-sig",newline="") as s:
        w=csv.writer(s);w.writerow(fields)
        for row in rows:
            w.writerow([json.dumps(row[k],ensure_ascii=False) if isinstance(row.get(k),(list,dict))
                        else row.get(k,"") for k in fields])


def measures(rows,events,scope,prior=()):
    cohort={k:r for k,r in rows.items() if (scope=="any_use" or (r["stratum"]=="first_observed" and k not in prior))}
    pos=set(cohort)&events.keys();out={"cohort":len(cohort),"observed":len(pos)}
    for arm,subset in (("paper",{k for k,r in cohort.items() if r["paper_vote"]>0}),
                        ("union",{k for k,r in cohort.items() if r["in_pool"]}),
                        ("hpg_only",{k for k,r in cohort.items() if r["route"]=="hpg_only"})):
        out[arm+"_size"]=len(subset);out[arm+"_hits"]=len(pos&subset)
    for s in ("base_score","text_score","score"):
        out[s+"_AP"]=average_precision(cohort,pos,s);out[s+"_R20pct"]=top_recall(cohort,pos,s)
    return out


def author_reference_dois():
    # Post-freeze bibliographic overlap check. No model-training features or targets are read into the ranking.
    with (PUBLIC/"data/processed_electrolytes.csv").open(encoding="utf-8-sig",newline="") as f:
        refs=[(r.get("reference") or "").strip().lower().removeprefix("https://doi.org/") for r in csv.DictReader(f)]
    return {r for r in refs if r.startswith("10.")},len(refs)


def export(home=ROOT/"runs"/"adoption"):
    dest=(ROOT/"results" if home.name=="adoption" else home/"results");dest.mkdir(parents=True,exist_ok=True)
    protocol=verified(home/"protocol.json");threshold=protocol["threshold_S_cm"]
    grid=verified(DATA/"physics/grid.json");all_rows=[];recipes=[];evals=[];winstats=[];event_table=[]
    graph_inputs={};pairs=[];case_candidates=[];unique_sources=set();unique_materials=set();unique_responses=set()
    refs=Counter();pending=Counter();reference_dois,public_rows=author_reference_dois()
    overlap={};sensitivity=[]
    for stream in ("broad","spe","independent"):
        seen=set()
        for path in (DATA/"intervals"/stream).glob("*.json"):
            d=verified(path);unique_responses.update(d["receipts"])
            refs[stream]+=len(d["records"]);pending[stream]+=sum(bool(r.get("unverified_claims")) for r in d["records"].values())
            seen.update(d["records"])
        overlap[stream]=sorted(reference_dois&seen)
    for year in YEARS:
        graph=verified(home/str(year)/"graph.json")
        snap=verified(home/str(year)/"forecast.json");rows=snap["rankings"]
        interval=next((DATA/"intervals"/"broad").glob(f"*_{year}.json"));graph_inputs.update(verified(interval)["records"])
        _,panel=build(graph_inputs,year);dated=dated_predictions(panel,grid,year)
        expected=admit((n for n,r in rows.items() if r["paper_vote"]>0),dated,year,threshold)
        if expected.keys()!={k for k,r in rows.items() if r["in_pool"]}:raise ValueError("Pool equality check failed")
        unique_sources.update(graph_inputs);unique_materials.update(rows)
        has_labels=year!=YEARS[-1];a=b={};reveal=None
        if has_labels:
            reveal=verified(home/str(year)/"reveal.json")
            other=verified(home/"external_verification"/f"{year+5}.json")
            if reveal["forecast"]!=snap["sha256"] or snap["sha256"] not in other["freezes"]:raise ValueError("Evaluation bound to wrong prediction")
            a=reveal["events"];b=other["events"]
            clean={k:kept for k,evs in a.items() if (kept:=[e for e in evs if e["doi"] not in reference_dois])}
            sensitivity.append({"cutoff":year,"scope":"first_observed","prior":"unchanged, frozen primary history",
                                **measures(rows,clean,"first_observed")})
            for p in reveal["pairs"]:pairs.append({"cutoff":year,**p})
            for name,evs,prior in (("primary",a,()),("disjoint",b,other["earlier_materials"])):
                for scope in ("any_use","first_observed"):
                    evals.append({"cutoff":year,"stream":name,"scope":scope,**measures(rows,evs,scope,prior)})
                for k,evidence in evs.items():
                    for ev in evidence:event_table.append({"cutoff":year,"stream":name,"material":k,**ev})
        status="closed" if has_labels else "open_2025_2029"
        rc=Counter(r["route"] for r in rows.values())
        qset={n for n,rs in dated.items() if any(qualifies(r,year,threshold) for r in rs)}
        stat={"cutoff":year,"documents":len(graph_inputs),"candidates":len(rows),"evaluable":len(dated),"high":len(qset),
              "paper_pool":rc["paper_only"]+rc["both"],"both":rc["both"],"extra":rc["hpg_only"],"pool":len(expected),
              "high25":sum(25 in rows[n]["temperatures_C"] for n in qset),"missed_high":len(qset-expected.keys()),
              "high_first":sum(rows[n]["stratum"]=="first_observed" for n in qset),
              "high_repeat":sum(rows[n]["stratum"]=="repeat" for n in qset),
              "passed_recipes":sum(len(r["qualifying_recipes"]) for r in rows.values()),"status":status,
              "extra_seen_primary":sum(n in a for n in rows if rows[n]["route"]=="hpg_only") if has_labels else None,
              "extra_seen_disjoint":sum(n in b for n in rows if rows[n]["route"]=="hpg_only") if has_labels else None}
        winstats.append(stat)
        for n,r in sorted(rows.items(),key=lambda z:z[1]["rank"]):
            source=min(panel[n]["sources"],key=lambda e:(e["year"],e["doi"]))
            best=max(r["qualifying_recipes"],key=lambda v:v["sigma_S_cm"],default={})
            ev1=a.get(n,[]);ev2=b.get(n,[])
            row={"cutoff":year,"material":n,"source_doi":source["doi"],"source_year":source["year"],
                 **{k:r.get(k) for k in ("route","in_pool","rank","pool_rank","text_rank","stratum","paper_vote","role",
                                         "source_count","base_score","text_score","score","hpg_evaluated","temperatures_C")},
                 "physical_vote":r["physical_judgment"].get("vote"),"best_sigma_S_cm":best.get("sigma_S_cm"),
                 "best_temp_C":best.get("temperature_C"),"best_salt_pct":best.get("salt_wt_pct"),"prior_SPE":r["past_spe_dois"],
                 "evaluation":status,"next_primary":len({e["doi"] for e in ev1}) if has_labels else None,
                 "next_disjoint":len({e["doi"] for e in ev2}) if has_labels else None,
                 "primary_doi":sorted({e["doi"] for e in ev1}),"disjoint_doi":sorted({e["doi"] for e in ev2})}
            all_rows.append(row)
            if r["route"]=="hpg_only" and has_labels:case_candidates.append(row)
            if n not in dated:continue
            counts=0
            for d in dated[n]:
                ok=qualifies(d,year,threshold);counts+=int(ok)
                recipes.append({"cutoff":year,**d,"qualifies":ok,"material_in_pool":r["in_pool"],"route":r["route"]})
            if counts!=len(r["qualifying_recipes"]):raise ValueError("Incorrect qualifying-recipe coverage")
    decisions={};controller_evidence=Counter();lookup=Counter()
    for f in (home/"decisions").rglob("*.json"):
        d=verified(f);decisions[d["sha256"]]=d
    for y in YEARS:
        f=verified(home/str(y)/"forecast.json")
        for h in f["paper_decisions"]+f["physical_decisions"]:
            d=decisions[h];unique_responses.update(d["receipts"]);controller_evidence[d["mode"]]+=len(d["receipts"])
            lookup.update(q["name"] for q in d["lookups"])
    for hit in unique_responses:
        if not any((RUN/"calls"/channel/(hit+".response.json")).is_file() for channel in ("extract","controller")):
            raise ValueError("Missing provider receipt "+hit)
    pair_stats={"pairs":len(pairs),"old_zero":sum(p["previous_zero"] for p in pairs),
          "new_zero":sum(not any(p["dx"]) for p in pairs),"both_abstained":sum(p["both_abstained"] for p in pairs)}
    excluded=[verified(home/"external_verification"/f"{y}.json") for y in YEARS]
    summary={"protocol_sha256":protocol["sha256"],"threshold_S_cm":threshold,"model":protocol["model"],
       "independent_source_papers":len(unique_sources),"unique_materials":len(unique_materials),"papers_by_stream":dict(refs),
       "papers_with_unverified_claims":dict(pending),"disjoint_verification_papers":sum(d["papers"] for d in excluded),
       "provider_responses":len(unique_responses),"controller_requests":dict(controller_evidence),"native_lookups":dict(lookup),
       "pairwise_learning":pair_stats,"windows":winstats,"metrics":evals}
    summary["hpg_reference_check"]={"public_modeling_rows":public_rows,"distinct_literal_DOIs":len(reference_dois),
        "overlap_by_retrieval":overlap,"primary_sensitivity":sensitivity,
        "scope":"DOI reference column in the public modeling table, without assigning training split or matching all formulations"}
    pool=[r for r in all_rows if r["in_pool"]]
    case=sorted(case_candidates,key=lambda r:(-int(bool(r["next_disjoint"] or r["next_primary"])),
                       -int(r["stratum"]=="first_observed"),
                       -r["cutoff"],r["pool_rank"],r["material"]))[:1]
    summary["case_selection"]="post-freeze illustration; prefer HPG-only materials with observed use and no recorded prior, then latest window, then highest pool rank"
    summary["case"]=case
    pe=next((r for r in all_rows if r["cutoff"]==2009 and r["material"]=="polyethylene" and r["route"]=="hpg_only"
             and "10.1021/ja502133j" in r["primary_doi"]),None)
    if pe:summary["manually_verified_case"]=pe
    write_json(dest/"summary.json",summary)
    for file,data,default in (("all_rankings.csv",all_rows,["cutoff","material"]),("adoption_pool.csv",pool,["cutoff","material"]),
          ("hpg_recipes.csv",recipes,["cutoff","material","recipe"]),("qualifying_recipes.csv",[r for r in recipes if r["qualifies"]],["cutoff","material","recipe"]),
          ("window_counts.csv",winstats,["cutoff"]),("metrics.csv",evals,["cutoff"]),("observed_spe.csv",event_table,["cutoff","stream","doi"]),
          ("overlap_sensitivity.csv",sensitivity,["cutoff"]),
          ("learning_pairs.csv",pairs,["cutoff","observed","unobserved"])):
        table(dest/file,data,list(data[0]) if data else default)
    render_summary(dest,summary)
    print("Completed",dest,flush=True)


def render_summary(dest,summary):
    w=summary["windows"];s=summary;t=s["threshold_S_cm"]
    lines=["# HPG 达标配方进入五年 SPE 应用预测池","",
        f"达标线为 {t:g} S/cm。每种已有文献依据且可编码的材料均试算 6 种干态 LiTFSI 参考配方，盐占 10%、20%、30 wt%，温度为 25 °C、60 °C，设定聚合度 100。任一配方达标即将该材料纳入预测池。材料在一个窗口只占一个名次，每个达标配方保留单独记录。","",
        f"跨领域来源共 {s['independent_source_papers']:,} 篇有 DOI 的论文，形成 {s['unique_materials']:,} 个文献具名候选。主核验检索 {s['papers_by_stream']['spe']} 篇，第二检索剔除与主核验及跨域检索重叠的 DOI 后保留 {s['disjoint_verification_papers']} 篇。各窗取累计可见文献。","",
        "| 截止年 | 候选 | 能算 HPG | HPG 达标 | 25 °C 达标 | 文献提名 | HPG 单独补入 | 合并预测池 | 漏纳达标材料 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in w:lines.append("| "+" | ".join(str(r[k]) for k in ("cutoff","candidates","evaluable","high","high25","paper_pool","extra","pool","missed_high"))+" |")
    total=sum(r["high"] for r in w);extra=sum(r["extra"] for r in w)
    lines+=["",f"五窗共有 {total} 条 HPG 达标的材料－窗口记录，其中 {extra} 条由 HPG 单独带入。相同材料可在不同窗口再次出现。"]
    lines+=["","## 后续五年的独立文献核验","",
        "下表统计已冻结名单中，后续窗口实际检得原句支持的固态聚合物电解质应用。主检索中已有应用史的材料计入复用层。独立 DOI 检索排除材料在两套检索中更早的应用后核算首次观察。未检得对应论文的材料保留为未观察。","",
        "| 截止年 | 核验检索 | 首次观察材料数 | 文献池命中 | 合并池命中 | 仅 HPG 增加命中 | 文献排序 AP | 综合排序 AP |",
        "|---|---|---:|---:|---:|---:|---:|---:|"]
    def num(x):return "无事件" if x is None else f"{x:.4f}"
    for r in s["metrics"]:
        if r["scope"]!="first_observed":continue
        lines.append(f"| {r['cutoff']} | "+("主检索" if r["stream"]=="primary" else "独立 DOI")+f" | {r['observed']} | {r['paper_hits']} | {r['union_hits']} | {r['hpg_only_hits']} | {num(r['text_score_AP'])} | {num(r['score_AP'])} |")
    lines+=["","准入规则改变名单覆盖。只改变准入、沿用相同分数时，全榜 AP 保持相等。表中的综合排序另计预先固定的 HPG 加分和主控读配方后的判断。各排序的分数均用于比较优先级。2024 年预测的 2025–2029 窗口仍开放。",""]
    if s["case"]:
        c=s["case"][0];ev=c["primary_doi"]+c["disjoint_doi"]
        name="聚己内酯（PCL）" if c["material"]=="polycaprolactone" else c["material"]
        lines+=["## 一个只因 HPG 入池的材料","",f"{c['cutoff']} 年，{name}的文献提名票为 {c['paper_vote']}。参考配方在 {c['best_temp_C']} °C、LiTFSI {c['best_salt_pct']} wt% 时得到 {c['best_sigma_S_cm']:.3g} S/cm，综合池内排名第 {c['pool_rank']}。跨域材料来源为 [DOI {c['source_doi']}](https://doi.org/{c['source_doi']})。",""]
        if "10.1021/acsami.2c02118" in ev and c["material"]=="polycaprolactone":
            lines+=["2022 年 Sångeland 等在实验中实际使用 PCL／LiTFSI 固态聚合物电解质并测量其电化学稳定性。后窗论文核实了聚合物和盐的采用，所引结果尚不足以校准本次 60 °C 参考配方的电导率。[2022 年 ACS 原论文](https://pubs.acs.org/doi/10.1021/acsami.2c02118)",""]
        else:lines+=[("后五年观察到该聚合物用于 SPE。"+" ".join(f"[核验论文](https://doi.org/{d})" for d in dict.fromkeys(ev))) if ev else "本次两套 SPE 检索均未观察到该材料在后五年的应用。",""]
    if s.get("manually_verified_case"):
        c=s["manually_verified_case"]
        lines+=["## 聚乙烯怎样从跨域文献进入 SPE 预测池","",
             f"2000 年的跨域论文研究低密度聚乙烯薄膜表面接枝。2009 年封榜时，文献主控对聚乙烯投 {c['paper_vote']} 票。理想聚乙烯／LiTFSI 配方在 {c['best_temp_C']} °C、盐占 {c['best_salt_pct']} wt% 时预测为 {c['best_sigma_S_cm']:.3g} S/cm，触发强制准入。聚乙烯在文献全榜第 {c['text_rank']}，在综合预测池第 {c['pool_rank']}。[2000 年跨域论文](https://www.nature.com/articles/pj2000146)","",
             "2014 年 Khurana 等在交联聚乙烯／聚氧化乙烯电解质中实际采用了聚乙烯链段，报告该体系在 25 °C 的电导率超过 10⁻⁴ S/cm。这条证据核实了预测窗口内的组分采用。HPG 数值对应另一套参考配方与温度，定量误差需要在同配方、同温度下评价。[2014 年 JACS 原论文](https://pubmed.ncbi.nlm.nih.gov/24754503/)",""]
    lines+=["## 解读范围","",
       "HPG 数值对应上述理想参考配方。后窗核验的单位是材料身份及其在 SPE 样品中的实际用途，论文可以采用不同盐、比例和温度。本次文献来源以 Polymer Journal 加一组跨领域专题检索为主，多数期刊条目只提供题名。应用史和首用结论均以检索覆盖为界。","",
       f"回测采用现代 DeepSeek 与 2025 年发表的 HPG 权重。HPG 作者公开建模表的参考文献列能解析出 {s['hpg_reference_check']['distinct_literal_DOIs']} 个不同 DOI。跨域来源重合 {len(s['hpg_reference_check']['overlap_by_retrieval']['broad'])} 篇，主 SPE 检索重合 {len(s['hpg_reference_check']['overlap_by_retrieval']['spe'])} 篇。按 DOI 从后窗核验移除这些论文后重新计算了[敏感性结果](overlap_sensitivity.csv)。这项核查保留已冻结的历史分层，各配方实际属于作者的哪个建模划分仍需单独核实。[HPG 作者仓库](https://github.com/spark8ku/HPG)","",
       "完整列表见 [预测池](adoption_pool.csv)、[逐配方计算](hpg_recipes.csv)、[后窗证据](observed_spe.csv)、[逐窗评价](metrics.csv) 和 [运行摘要](summary.json)。"]
    (dest/"五窗应用预测结果.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


if __name__=="__main__":export()
