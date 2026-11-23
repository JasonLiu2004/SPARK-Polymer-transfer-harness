"""Produce the human-readable comparison from frozen forecasts and the identical-cohort metric table."""
import argparse
import csv
from evidence import ROOT,YEARS,read_json,verified
from explain import trace
from ordinal import positions
from ranking_policy import DEFAULT_RUN, EXPOSURE


def number(x):
    return "无可评事件" if x is None else f"{x:.4f}"


def interval_text(bounds):
    if bounds is None:return "未入池"
    return str(bounds[0]) if bounds[0]==bounds[1] else f"{bounds[0]}–{bounds[1]}"


def comparison_summary(scores):
    rows = ["## 在相同候选上比较首次采用排序", "",
            "每个有首次观察事件的截止窗占相同权重。前十命中报这些窗口的合计。两套 SPE 检索分别评价。", "",
            "| SPE 核验 | 有事件的窗口 | 事件数 | 篇数与近期／旧加分法／新主控的平均 AP | 三种方法的前十命中 |",
            "|---|---:|---:|---:|---:|"]
    for source, label in (("primary","主检索"), ("disjoint","去重 DOI")):
        methods = {}
        for method in ("frequency_recency","previous","agent"):
            data = [r for r in scores if r["source"]==source and r["universe"]=="whole_panel"
                    and r["target"]=="first_observed" and r["method"]==method and r["observed"]]
            methods[method] = {r["cutoff"]:r for r in data}
        common = set.intersection(*(set(data) for data in methods.values()))
        if not common:
            continue
        averages = " / ".join(f"{sum(data[y]['AP'] for y in common)/len(common):.4f}" for data in methods.values())
        hits = " / ".join(f"{sum(data[y]['hits_at_10'] for y in common):g}" for data in methods.values())
        observed = sum(methods["agent"][y]["observed"] for y in common)
        rows.append(f"| {label} | {len(common)} | {observed} | {averages} | {hits} |")
    return rows + ["", "逐材料表可对照每个后来观察到的材料在三种排名中的位置、HPG 达标条件数、实际样品角色与核验 DOI。[首次采用材料的名次与论文](observed_first_use_ranks.csv)", ""]


def exposure_summary(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = ["## 篇数与最近发表年份相同的材料如何排", "",
              "这项补充诊断把有后窗采用记录的候选与同一窗中篇数、最近年份完全相同的未观察候选比较。报告主控把有采用记录者排在前面的比例，并列算半次。每份检索单列，多个材料对可能共享同一项采用事件。", "",
              "| SPE 核验 | 有同条件对照的采用事件 | 对数 | 新主控排在前面 | 并列 | 排在后面 | 含并列的优先比例 |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for source,label in (("primary","主检索"),("disjoint","去重 DOI")):
        chosen = [r for r in rows if r["verification_source"]==source and r["method"]=="agent"]
        pos,pairs,ahead,tied,behind = (sum(int(r[k]) for r in chosen) for k in
                                        ("observed_with_exposure_peers","pairs","ahead","tied","behind"))
        rate = f"{(ahead+0.5*tied)/pairs:.1%}" if pairs else "—"
        result.append(f"| {label} | {pos} | {pairs} | {ahead} | {tied} | {behind} | {rate} |")
    return result + ["", "在该配对条件下，篇数与近期基线对每一对都给出并列。[逐窗对照](same_exposure_pairs.csv)", ""]


def constrained_summary(dest, scores):
    with (dest/"exposure_order_metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        metrics=list(csv.DictReader(stream))
    result=["## 主控在文献覆盖约束下的探索性对照","",
            "如果 A 的跨域论文篇数至少与 B 相同，且最近发表年份至少与 B 一样近，其中一项更强，就保留 A 在 B 之前。每一步在已经满足这些条件的候选中，取主控比较后最优的一档。两项证据各有优劣时由主控决定。篇数与最近时间两个指标都落后的材料，仍保留全榜和相应的池内名次。另做一份对照，把每批允许选取的材料全部并列。","",
            "这项分析在查看部分历史结果与原文冻结权重后设计，复用当时已提交的主控比较，没有新增模型请求。两份排序共享全部候选、HPG 准入与 SPE 标签。","",
            "| SPE 核验 | 篇数与近期基线 | 自由主控 | 仅文献约束、同层并列 | 文献约束下主控选序 | 前十命中（仅约束／约束加主控） |",
            "|---|---:|---:|---:|---:|---:|"]
    for src,label in (("primary","主检索"),("disjoint","去重 DOI")):
        ref={r["method"]:[] for r in scores if r["source"]==src}
        for r in scores:
            if r["source"]==src and r["target"]=="first_observed" and r["universe"]=="whole_panel" and r["observed"]:
                ref[r["method"]].append(r["AP"])
        extras={m:[r for r in metrics if r["source"]==src and r["method"]==m and int(r["observed"])]
                for m in ("exposure_fronts","exposure_agent")}
        if not extras["exposure_agent"]:
            continue
        def average(items):
            return number(sum(items)/len(items)) if items else "—"
        lead=" | ".join(average(ref.get(k,[])) for k in ("frequency_recency","agent"))
        add=" | ".join(average([float(r["AP"]) for r in x]) for x in extras.values())
        hits=" / ".join(f"{sum(float(r['hits_at_10']) for r in x):g}" for x in extras.values())
        result.append(f"| {label} | {lead} | {add} | {hits} |")
    return result+["","各列均为有事件窗口等权的平均 AP。[补充方案代码](../../../evidence_order.py) · [逐窗指标](exposure_order_metrics.csv) · [2024 前瞻池](2024_exposure_first_adoption.csv)",""]


def render_primary(home,summary):
    dest=home/"results"
    windows=summary["windows"]
    rows=["# 五窗应用预测 · 文献约束下的 LLM 主控排序","",
          "每个截止年先封存正式全榜和推荐池，再用随后五年的固态聚合物电解质论文查证具名聚合物的应用。篇数与最近发表年份共同确定部分材料的先后，主控根据三轴结构、样品角色和 HPG 配方比较其他候选。闭窗反馈使用该窗的正式名次。","",
          "| 截止年 | 候选数 | 入池数 | HPG 达标且入池／达标 | 正式优先级数 |","|---|---:|---:|---:|---:|"]
    for w in windows:
        rows.append(f"| {w['cutoff']} | {w['candidates']} | {w['agent_pool']} | {w['qualifying_admitted']}/{w['qualifying_hpg']} | {w['tiers']} |")
    methods=("exposure_primary","llm_unconstrained","exposure_fronts","frequency_recency","previous")
    scores=[r for r in summary["metrics"] if r["target"]=="first_observed" and r["universe"]=="whole_panel"]
    rows+=["","## 首次采用的同候选对照","",
           "各列均为平均精度 AP，值越大表示后来被观察采用的材料越集中在前排。汇总对有事件的时间窗等权。自由 LLM 列使用本次模型比较和本次记忆，仅移除文献顺序约束。仅文献约束列将每批可选候选并列。","",
           "| SPE 核验 | 时间窗 | 首次采用事件 | 正式排序 | 自由 LLM | 仅文献约束 | 篇数与近期 | 旧加分法 |",
           "|---|---|---:|---:|---:|---:|---:|---:|"]
    for source,label in (("primary","主检索"),("disjoint","去重 DOI")):
        totals={method:[] for method in methods}
        event_count=0
        for year in YEARS[:-1]:
            window={r["method"]:r for r in scores if r["source"]==source and r["cutoff"]==year}
            events=window["exposure_primary"]["observed"]
            event_count+=events
            cells=[]
            for method in methods:
                ap=window.get(method,{}).get("AP")
                cells.append("—" if ap is None else f"{ap:.4f}")
                if ap is not None:
                    totals[method].append(ap)
            rows.append(f"| {label} | {year+1}–{year+5} | {events} | "+" | ".join(cells)+" |")
        event_windows=len(totals["exposure_primary"])
        averages=[f"{sum(values)/len(values):.4f}" if values and len(values)==event_windows else "—" for values in totals.values()]
        rows.append(f"| {label} | **事件窗均值** | {event_count} | "+" | ".join(averages)+" |")
    if 2009 in YEARS[:-1]:
        feedback=verified(home/"2009"/"reveal.json")
        case=feedback["training_cases"].get("polyethylene")
        if case and case["next_window_specimen"]:
            frozen=verified(home/"2009"/"forecast.json")["rows"]["polyethylene"]
            basis=case["basis_of_frozen_rank"];use=case["next_window_specimen"]
            role={"host":"基体","cohost":"共基体","reinforcement":"增强组分","filler":"填料"}.get(use["role"],use["role"])
            rows+=["","## 一次实际的闭窗反馈","",
                   f"2009 年聚乙烯有 {basis['distinct_pre_cutoff_DOIs']} 篇跨域来源，最近发表年份为 {basis['latest_source_year']}。主控原始偏好为全榜第 {interval_text(basis['agent_preference_before_constraint'])}，正式全榜第 {interval_text(case['frozen_rank_range'])}，推荐池名次为 {interval_text(frozen['pool_rank'])}。后窗论文在 {use['year']} 年观察到它在电解质样品中承担{role}角色。这两个名次、当时的文献覆盖和后窗样品一同进入了复盘。[核验论文](https://doi.org/{use['doi']}) · [闭窗案例与记忆](../2009/reveal.json)"]
    latest=summary["evidence_coverage"][-1]
    last_year=windows[-1]["cutoff"]
    rows+=["","## 前瞻名单与证据","",
           f"{last_year} 年封存的名单预测 {last_year+1}–{last_year+5} 年的论文应用。首次采用表示截止当年在本次 SPE 检索中尚无采用记录。表中保留正式名次、主控原始偏好名次、文献提名 DOI 与 HPG 达标条件。[首次采用推荐池]({last_year}_first_adoption.csv) · [各窗全榜](rankings.csv)","",
           f"截至 {last_year} 年使用 {latest['papers']:,} 条跨域题录，其中 {latest['papers_with_abstract_excerpts']} 条含摘要摘句。本轮沿用既有语料和 HPG 配方。第二套核验共有 {summary['disjoint_papers']} 篇 DOI 与主检索及跨域语料均不同的论文。[证据覆盖](evidence_coverage.csv) · [首次观察材料与核验论文](observed_first_use_ranks.csv)","",
           "排序规则来自先前的历史探索。这里的历史表现衡量该规则接入逐窗反馈后的结果。各窗揭晓时，主控读取正式名次、自由偏好名次和当时的文献覆盖，形成下一窗取证问题。[逐窗指标](metrics.csv) · [运行协议](../protocol.json)"]
    if (dest/"audit.json").exists():
        proof=read_json(dest/"audit.json")
        rows+=["",f"已从 {proof['unique_provider_responses']:,} 个不同的模型响应重建 {proof['material_window_rows']:,} 条材料－窗口名次，其中 {proof['provider_receipts_predating_protocol']:,} 个响应在本协议登记前已有可校验记录。[离线核验](audit.json)"]
    (dest/"五窗排序对照.md").write_text("\n".join(rows)+"\n",encoding="utf-8")


def render(home):
    dest=home/"results";s=read_json(dest/"summary.json");windows=s["windows"];scores=s["metrics"]
    if s.get("primary_ranking")==EXPOSURE:
        return render_primary(home,s)
    rows=["# 智能体按证据排序的五窗回测","",
      "预测目标是某种具名聚合物是否会在随后五年的论文中成为实测固态聚合物电解质的一部分。候选来自独立跨域文献抽取，后窗核验只读 SPE 论文。数值越高的平均精度（AP）意味着后来被观察到的材料越集中在榜首。并列位置用期望值评价。","",
      "| 截止年 | 全部候选 | 主控给出的优先级数 | 最大并列组 | 新推荐池 | 旧推荐池 | 达标且入池／HPG 达标 |",
      "|---|---:|---:|---:|---:|---:|---:|"]
    for w in windows:
        rows.append(f"| {w['cutoff']} | {w['candidates']} | {w['tiers']} | {w['largest_tie']} | {w['agent_pool']} | {w['previous_pool']} | {w['qualifying_admitted']}/{w['qualifying_hpg']} |")
    rows+=["","新主控重新做文献提名，所以推荐池大小可以改变。以下两项排序对照均固定候选身份和后窗标签。首次观察以该检索在截止年以前的材料记录为界。不同检索的材料可以重合，第二套检索保留去重 DOI。",""]
    rows+=comparison_summary(scores)
    for scope,title in [("whole_panel","全体尚无已知应用的具名候选"),("previous_fixed_pool","同一份旧推荐池中的首次应用候选")]:
        rows+=["## "+title,"","| 截止年 | SPE 核验 | 实际观察数 | 篇数与近期基线 AP | 旧加分法 AP | 新主控 AP | 旧／新前十命中 |",
               "|---|---|---:|---:|---:|---:|---:|"]
        for y in YEARS[:-1]:
            for source,label in (("primary","主检索"),("disjoint","去重 DOI")):
                v={r["method"]:r for r in scores if r["cutoff"]==y and r["source"]==source and r["target"]=="first_observed" and r["universe"]==scope}
                if "agent" not in v:continue
                a=v["agent"];old=v.get("previous",{})
                old_top=old.get("hits_at_10")
                pair=(f"{old_top:g}" if old_top is not None else "—")+f" / {a['hits_at_10']:g}"
                rows.append(f"| {y} | {label} | {a['observed']} | {number(v.get('frequency_recency',{}).get('AP'))} | {number(old.get('AP'))} | {number(a['AP'])} | {pair} |")
        rows.append("")
    rows+=exposure_summary(dest/"same_exposure_pairs.csv")
    rows+=constrained_summary(dest,scores)
    p=verified(home/"2009"/"forecast.json")["rows"].get("polyethylene")
    if p:
        threshold_case = verified(home/"2009"/"reveal.json")["events"].get("polyethylene",[])
        example = next((e for e in threshold_case if e["doi"]=="10.1021/ja502133j"),None)
        if example and p["qualifying_recipes"]:
            recipe = max(p["qualifying_recipes"], key=lambda r:r["sigma_S_cm"])
            rows+=["## 达标准入与后窗实证如何连接","",
                   f"2009 年的聚乙烯以干态 LiTFSI {recipe['salt_wt_pct']:g} wt%、{recipe['temperature_C']:g} °C 的 HPG 预测 {recipe['sigma_S_cm']:.2e} S/cm 入池。全榜第 {interval_text([p['rank_min'],p['rank_max']])}，池内第 {interval_text(p['pool_rank'])}。2014 年的论文观察到交联聚乙烯／聚氧化乙烯固态电解质，聚乙烯承担共基体角色。两项证据的配方不同。主控据此给下一窗留下一个取证问题，要求查找常见结构聚合物与导离子伙伴形成交联膜或共混膜的早期证据。[采用该材料的论文](https://doi.org/10.1021/ja502133j) · [该窗的排名与反馈](../2009/reveal.json)",""]
    rows+=["## 一条可以回查的比较路径",""]
    f=verified(home/"2019"/"forecast.json")
    if "polycaprolactone" in f["rows"]:
        case=trace(home,2019,"polycaprolactone");r=f["rows"]["polycaprolactone"]
        dos=verified(home/"2019"/"reveal.json")["events"].get("polycaprolactone",[])
        rows+=[f"2019 年聚己内酯的全榜名次为 {interval_text(case['full_rank'])}，池内名次为 {interval_text(case['pool_rank'])}。比较记录共有 {len(case['comparisons'])} 层，准入途径为"+{"hpg_only":"HPG 达标","both":"文献提名和 HPG 达标","paper_only":"文献提名","outside":"待观察"}[r["route"]]+"。",""]
        eligible={n for n,x in f["rows"].items() if x["stratum"]=="first_observed"}
        if "polycaprolactone" in eligible:
            constrained=verified(home/"exposure_order/2019.json")
            original_rank=positions(f["tiers"],eligible)["polycaprolactone"]
            evidence_rank=positions(constrained["tiers"],eligible)["polycaprolactone"]
            rows+=[f"将比较范围固定为当时尚无采用记录的 {len(eligible)} 种材料，聚己内酯在自由主控榜排第 {interval_text(original_rank)}，在文献覆盖约束下排第 {interval_text(evidence_rank)}。两份榜名次变化来自同一材料与其他候选的先后关系，HPG 配方与提名资格相同。",""]
        if dos:
            e=next((d for d in dos if d["doi"]=="10.1021/acsami.2c02118"),dos[0])
            rows+=[f"随后检索到 {len({d['doi'] for d in dos})} 篇含该材料的合格 SPE 论文。其中一篇在 {e['year']} 年将其用于电解质，抽取角色为 {e['role']}。[核验论文](https://doi.org/{e['doi']})",""]
        rows+=["从项目目录运行以下命令可看到每个参照组、主控选择的位置、组级比较理由与来源。","","~~~powershell",f"python -X utf8 -B explain.py --run-id {home.name} --year 2019 --material polycaprolactone","~~~",""]
    latest = s["evidence_coverage"][-1]
    rows+=["## 可用证据的覆盖范围","",
           f"{latest['cutoff']} 年的跨域检索有 {latest['papers']:,} 条题录，其中 {latest['papers_with_abstract_excerpts']} 条带有摘要摘句。{latest['candidates']} 个候选中，{latest['single_source_materials']} 个只关联一篇跨域论文。骨架、有机阳离子、阴离子分别在 {latest['backbone']}、{latest['organic_cation']}、{latest['anion']} 个候选中有直接抽取记录。{latest['three_axes_in_same_evidence_row']} 个候选有同一证据行的三轴记录，{latest['HPG_evaluable']} 个具备已登记的 HPG 配方。各窗的文献与角色覆盖可逐项核对。[证据覆盖表](evidence_coverage.csv)","",
           "## 评价范围","",
           f"独立验证检索保留 {s['disjoint_papers']} 篇与主检索及跨域语料 DOI 均不重合的论文。2004、2009、2014、2019 截止窗已完整揭晓，2024 年榜预测 2025–2029 年。论文索引中的未观察材料保持未确认。","",
           "这些结果来自一套固定参照抽样和一个现代 DeepSeek 模型。采用时间截断的文献与记忆仍可能受基础模型预训练年代影响。当前实验比较完整方法，尚未单独估计改变参照抽样、去掉历史记忆或隐藏 HPG 读数各自的因果效应。","",
           "[全榜](rankings.csv) · [全部入池材料](adoption_pool.csv) · [2024 首次采用预测池](2024_first_adoption.csv) · [全部指标](metrics.csv) · [候选池覆盖](pool_coverage.csv)"]
    if (dest/"audit.json").exists():
        audit=read_json(dest/"audit.json");rows+=["",f"离线核验从 {audit['unique_provider_responses']:,} 个不同的真实模型响应重建了 {audit['material_window_rows']:,} 条材料－窗口名次，逐项核对 HPG 达标准入。[核验凭据摘要](audit.json)"]
    (dest/"五窗排序对照.md").write_text("\n".join(rows)+"\n",encoding="utf-8")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--run-id",default=DEFAULT_RUN)
    render(ROOT/"runs"/p.parse_args().run_id)
