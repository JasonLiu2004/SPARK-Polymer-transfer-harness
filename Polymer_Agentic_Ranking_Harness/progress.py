"""Export the verified primary forecasts of a running or interrupted study."""
from evidence import DATA, INTERVALS, merge_interval, verified, write_json
from evaluate import cutoff_sources, hpg_coverage, metrics, write_table
from ordinal import positions


def export_available(home, proof):
    dest = home / "progress"
    stats = {s["year"]: s for s in proof["verified_windows"]}
    closed = set(proof["revealed_cutoffs"])
    grid = verified(DATA / "physics/grid.json")["designs"]
    broad = {}
    rankings = []
    summary = ["# 已封存的推荐与反馈", "",
               "名次来自各窗正式预测。后五年观察数只取已揭晓窗口的 SPE 主检索。AP 在该窗尚无已知采用的全部候选上计算。", "",
               "| 截止年 | 全榜 | 入池 | HPG 达标且入池 | 后窗首次观察 | 正式 AP | 自由 LLM AP |",
               "|---|---:|---:|---:|---:|---:|---:|"]
    for lo,year in INTERVALS:
        if year not in stats:
            break
        section = home / str(year)
        forecast = verified(section / "forecast.json")
        if forecast["sha256"] != stats[year]["forecast_sha256"]:
            raise ValueError("Forecast changed after its audit")
        merge_interval(broad, verified(DATA/"intervals/broad"/f"{lo}_{year}.json"))
        graph = verified(section/"graph.json")
        sources = cutoff_sources(graph, broad)
        rows = forecast["rows"]
        first = {n for n,r in rows.items() if r["stratum"]=="first_observed"}
        selected = {n for n in first if rows[n]["in_pool"]}
        first_in_pool = positions(forecast["tiers"], selected)
        events = verified(section/"reveal.json")["events"] if year in closed else {}
        for tier in forecast["tiers"]:
            for name in sorted(tier):
                r = rows[name]
                p = r["pool_rank"] or (None,None)
                first_rank = first_in_pool.get(name,(None,None))
                nomination = r["paper_nomination"] or {}
                rankings.append({
                    "cutoff":year, "forecast_start":forecast["horizon"][0], "forecast_end":forecast["horizon"][1],
                    "material":name, "primary_rank_min":r["rank_min"], "primary_rank_max":r["rank_max"],
                    "llm_rank_min":r.get("llm_rank_min",r["rank_min"]), "llm_rank_max":r.get("llm_rank_max",r["rank_max"]),
                    "stratum":r["stratum"], "in_pool":r["in_pool"], "route":r["route"], "pool_rank_min":p[0], "pool_rank_max":p[1],
                    "first_use_pool_rank_min":first_rank[0], "first_use_pool_rank_max":first_rank[1],
                    "source_papers":r["source_count"], "latest_source_year":r["latest_source"],
                    "paper_nomination_doi":nomination.get("doi",""), "qualifying_hpg_recipes":len(r["qualifying_recipes"]),
                    **sources[name], **hpg_coverage(grid.get(name,[]),r["qualifying_recipes"]),
                    "primary_outcomes_opened":year in closed,
                    "observed_spe_dois":"|".join(sorted({e["doi"] for e in events.get(name,[])})) if year in closed else None,
                })
        observed = left = right = "—"
        if year in closed:
            observed = str(len(first & events.keys()))
            def mean_precision(field):
                scores = {n:-rows[n].get(field,rows[n]["rank_min"]) for n in first}
                ap = metrics(scores,events)["AP"]
                return f"{ap:.4f}" if ap is not None else "—"
            left, right = mean_precision("rank_min"), mean_precision("llm_rank_min")
        s = stats[year]
        summary.append(f"| {year} | {len(rows)} | {s['admitted']} | {s['high_admitted']} | {observed} | {left} | {right} |")
    planned = proof["planned_cutoffs"]
    pending = [y for y in planned if y not in stats]
    latest = max(stats, default=None)
    fields = list(rankings[0]) if rankings else ["cutoff","material","primary_rank_min","primary_rank_max","in_pool","route"]
    write_table(dest/"sealed_rankings.csv",rankings,fields)
    prediction_fields = [k for k in fields if k not in ("primary_outcomes_opened","observed_spe_dois")]
    latest_pool = [{k:r[k] for k in prediction_fields} for r in rankings
                   if r["cutoff"]==latest and r["first_use_pool_rank_min"] is not None]
    write_table(dest/"latest_first_adoption.csv", latest_pool, prediction_fields)
    summary += ["",f"已封存 {len(stats)}/{len(planned)} 个截止窗，共 {proof['material_window_rows']:,} 条材料－窗口名次。"
                f"已复核其中 {proof['unique_provider_responses']:,} 个不同的模型响应。"]
    if pending:
        summary += ["", "待生成正式名单的截止年为 "+ "、".join(map(str,pending))+"。"]
    if latest is not None:
        summary += ["",f"最近一份已封榜名单的截止年为 {latest}，预测 {latest+1}–{latest+5} 年。"
                    "推荐池表只含截止年可见证据，逐材料全榜另附已揭晓窗口的核验 DOI。"
                    "[该窗首次采用推荐池](latest_first_adoption.csv) · [全部已封存名次](sealed_rankings.csv) · [核验记录](audit.json)"]
    (dest/"已封存窗口.md").write_text("\n".join(summary)+"\n",encoding="utf-8")
    write_json(dest/"audit.json",proof)
