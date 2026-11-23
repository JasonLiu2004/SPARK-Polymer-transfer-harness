import unittest
from contextlib import ExitStack, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from agent import ToolSession,decode_arguments,parse_order,parse_placements
from evaluate import hpg_coverage, metrics
from evidence import AXES, seal, verified
from explain import recommendations
from memory import closed_cases
from ranking_policy import EXPOSURE, ORDINAL, apply_exposure_policy, ranking_record, select_policy
from ordinal import positions,rank_all


class Oracle:
    class View:
        year=2004
    view=View()

    def __init__(self,prefs):
        self.prefs=prefs

    def decide(self,mode,names,salt,landmarks=()):
        if mode=="order":
            values=sorted({self.prefs[n] for n in names})
            answer={"tiers":[[n for n in names if self.prefs[n]==v] for v in values]}
        else:
            place={}
            for n in set(names)-set(landmarks):
                place[n]="TAIL"
                for i,pivot in enumerate(landmarks,1):
                    if self.prefs[n]<=self.prefs[pivot]:
                        place[n]=("E" if self.prefs[n]==self.prefs[pivot] else "S")+str(i)
                        break
            answer={"placements":place}
        return {"result":answer,"contract":"fixture"}


class OrdinalTests(unittest.TestCase):
    def test_adaptive_partition_preserves_all_ties_and_preferences(self):
        for modulus in (1,4,37):
            prefs={f"poly-{i}":(17*i)%modulus for i in range(37)}
            tiers,_=rank_all(Oracle(prefs),list(reversed(prefs)),4,leaf=5,landmarks=3,chunk=4)
            self.assertEqual([set(t) for t in tiers],[{n for n in prefs if prefs[n]==v} for v in sorted(set(prefs.values()))])
            subset={n for n in prefs if n.endswith(("2","3"))}
            projected=positions(tiers,subset)
            self.assertEqual(set(projected),subset)
            self.assertEqual(max(hi for lo,hi in projected.values()),len(subset))

    def test_singleton_and_empty(self):
        self.assertEqual(rank_all(Oracle({}),[],1),([],{}))
        self.assertEqual(rank_all(Oracle({"a":0}),["a"],1)[0],[["a"]])

    def test_require_complete_locally_grounded_partitions(self):
        self.assertEqual(parse_order("K2 = K1 > K3",["K1","K2","K3"]),[["K2","K1"],["K3"]])
        with self.assertRaises(ValueError):parse_order("K1 > K1",["K1","K2"])
        with self.assertRaises(ValueError):parse_placements([{"slot":"S1","codes":["K1"]}],{"K2"},1)
        with self.assertRaises(ValueError):parse_placements([{"slot":"E2","codes":["K2"]}],{"K2"},1)
        self.assertEqual(decode_arguments('{"arguments":"{\\"codes\\":[\\"all\\"]}"}'),{"codes":["all"]})
        with self.assertRaises(ValueError):decode_arguments('{"codes":[]} unknown')

    def test_citations_and_physical_results_must_be_read(self):
        class View:
            year=2004
            physical={"a": [{}]}
        s=ToolSession("order",View(),["a","b"],[],"fixture")
        s.seen.update(s.mapping)
        for c in s.mapping:s.facets_seen[c].update(AXES)
        for c in s.mapping:s.cite(c,"P1","10.1234/"+c.lower())
        good={"order":"K2 > K1","because":"different specimen roles",
              "evidence":["K1.P1 (10.1234/k1)","K2.P1 (10.1234/k2)"]}
        with self.assertRaises(ValueError):s.submit(good)
        s.hpg_seen.update(s.mapping)
        self.assertEqual(s.submit(good)["tiers"],[[s.mapping["K2"]],[s.mapping["K1"]]])
        with self.assertRaises(ValueError):s.submit({**good,"evidence":["K1.P1 (10.1234/k2)","K2.P1"]})

    def test_tie_aware_evaluation(self):
        stats=metrics({"a":0,"b":0},{"a"})
        self.assertEqual(stats["AP"],0.75)
        self.assertEqual(stats["hits_at_10"],1)
        self.assertIsNone(metrics({"a":0},set())["AP"])

    def test_exposure_order_uses_the_agent_on_incomparable_materials(self):
        from evidence_order import constrained_tiers
        def row(count, year, rank):
            return {"source_count":count,"latest_source":year,"rank_min":rank}
        rows={"A":row(4,2001,5),"B":row(2,2004,3),"C":row(2,1999,1),"D":row(4,2001,5)}
        self.assertEqual(constrained_tiers(rows),[["B"],["A","D"],["C"]])
        self.assertEqual(constrained_tiers(rows,False),[["A","B","D"],["C"]])
        rows["A"]["rank_min"]=2
        self.assertEqual(constrained_tiers(rows),[["A"],["B"],["D"],["C"]])

    def test_registered_run_keeps_its_method(self):
        with TemporaryDirectory() as directory:
            home=Path(directory)
            self.assertEqual(select_policy(home),EXPOSURE)
            seal(home/"protocol.json",{"cutoffs":[2004],"rank":"old ordinal"})
            self.assertEqual(select_policy(home),ORDINAL)
            with self.assertRaisesRegex(ValueError,"new --run-id"):
                select_policy(home,EXPOSURE)

    def test_constrained_forecast_rejects_missing_duplicate_and_future_evidence(self):
        one={"papers":1,"latest":2004}
        panel={"A":one,"B":one}
        for bad in ([["A"]],[["A"],["A"]],[["A"],[],["B"]],[["C","B"]]):
            with self.subTest(tiers=bad),self.assertRaises(ValueError):
                apply_exposure_policy(panel,bad,2004)
        with self.assertRaisesRegex(ValueError,"dated publication"):
            apply_exposure_policy({"A":{"papers":2,"latest":2005}},[["A"]],2004)
        self.assertEqual(ranking_record(EXPOSURE,[],{},2004,set()),([],{}, {},{}))

    def test_feedback_uses_the_primary_order_and_preserves_hpg_pool(self):
        panel={"A":{"papers":3,"latest":2004},"B":{"papers":2,"latest":2004},"C":{"papers":1,"latest":2002}}
        # C is HPG-only. The LLM would put C first and A last.
        prefs=[["C"],["B"],["A"]]
        tiers,final,within,model=ranking_record(EXPOSURE,prefs,panel,2004,{"B","C"})
        self.assertEqual(tiers,[["A"],["B"],["C"]])
        self.assertEqual((within["C"],model["C"]),((2,2),(1,1)))
        rows={}
        for n,item in panel.items():
            rows[n]={"rank_min":final[n][0],"rank_max":final[n][1],"llm_rank_min":model[n][0],"llm_rank_max":model[n][1],
                     "in_pool":n in within,"route":"hpg_only" if n=="C" else "paper_only" if n=="B" else "outside",
                     "source_count":item["papers"],"latest_source":item["latest"],"stratum":"first_observed"}
        class View:
            def publications(self,name,extended=False):
                return {"sample_evidence":[{"doi":"10.0000/early-"+name}]}
        later={"year":2008,"doi":"10.0000/later","name":"C","sample":"film","role":"cohost","quote":"C in a film","axes":{}}
        cases,counts=closed_cases({"rows":rows,"primary_ranking":EXPOSURE},{"C":[later]},View())
        self.assertEqual(set(cases),{"B","C"})
        self.assertEqual(cases["C"]["frozen_rank_range"],[3,3])
        self.assertEqual(cases["C"]["basis_of_frozen_rank"]["agent_preference_before_constraint"],[1,1])
        self.assertEqual(counts["pool_hits"],1)

    def test_missing_hpg_evidence_is_exported_separately_from_a_low_prediction(self):
        calculated={"status":"predicted"}
        self.assertEqual(hpg_coverage([],[])["hpg_status"],"no_registered_design")
        self.assertEqual(hpg_coverage([{"status":"failed"}],[])["hpg_status"],"no_valid_prediction")
        self.assertEqual(hpg_coverage([calculated],[])["hpg_status"],"below_threshold_on_computed_recipes")
        self.assertEqual(hpg_coverage([calculated],[calculated])["hpg_status"],"passed_threshold")

    def test_default_pipeline_seals_primary_ranks_before_reveal_and_learns_from_them(self):
        # The parent workspace has several scripts named run.py.
        spec=spec_from_file_location("tested_polymer_forecast",Path(__file__).with_name("run.py"))
        run=module_from_spec(spec)
        spec.loader.exec_module(run)
        first,second="polyethylene","polystyrene"
        def paper(doi,year,name,stage):
            item={"name":name,"name_ref":"T","sample":"film","role":"host","evidence_ref":"T",**dict.fromkeys(AXES,"")}
            return {"doi":doi,"year":year,"stage":stage,"materials":[item],"solid_ref":"T","device_ref":"T",
                    "segments":{"T":name+" specimen"}}
        broad=[paper("10.0000/a",2003,first,"general_polymer"),paper("10.0000/b",2004,first,"general_polymer"),
               paper("10.0000/c",2001,second,"general_polymer")]
        event=paper("10.0000/later",2008,second,"solid_sample")
        design={"material":second,"recipe":"fixture","status":"predicted","temperature_C":25,"sigma_S_cm":0.0002}
        lesson={"when":"subsequent window","question":"Is there a specimen?","countercheck":"Check the role","doi":event["doi"]}
        with TemporaryDirectory() as folder, ExitStack() as stack:
            home=Path(folder)/"trial"
            memories={}
            def interval(stream,lo,hi,workers):
                records=[]
                if stream=="broad" and hi==2004:
                    records=broad
                if stream=="spe" and hi==2009:
                    forecast=verified(home/"2004"/"forecast.json")
                    self.assertEqual(forecast["tiers"],[[first],[second]])
                    self.assertEqual(forecast["rows"][second]["llm_rank_min"],1)
                    self.assertEqual(forecast["rows"][second]["pool_rank"],[1,1])
                    self.assertFalse((home/"2004"/"reveal.json").exists())
                    visible=recommendations(home,2004)
                    self.assertEqual(visible["forecast_sha256"],forecast["sha256"])
                    self.assertEqual([r["material"] for r in visible["candidates"]],[second])
                    records=[event]
                return {"sha256":f"{stream}-{hi}","records":{p["doi"]:p for p in records}}
            def agent(section,view,memory,model_name):
                memories[view.year]=list(memory)
                def decide(mode,names,salt,cases):
                    self.assertEqual(mode,"reflect")
                    self.assertEqual(cases[second]["frozen_rank_range"],[2,2])
                    self.assertEqual(cases[second]["basis_of_frozen_rank"]["agent_preference_before_constraint"],[1,1])
                    return {"contract":"fixture","result":{"lessons":[lesson]}}
                return SimpleNamespace(view=view,decide=decide)
            def check_final(location,source,seen):
                self.assertEqual(verified(location/"2009"/"forecast.json")["memory"],memories[2009])
                self.assertFalse((location/"2009"/"reveal.json").exists())
            stack.enter_context(patch.multiple(run,YEARS=(2004,2009),INTERVALS=((1950,2004),(2005,2009)),
                                              read_interval=interval,window_agent=agent))
            stack.enter_context(patch.object(run,"Model",return_value=SimpleNamespace(model="test")))
            stack.enter_context(patch.object(run,"prepare",return_value={"sha256":"fixture","designs":{second:[design]}}))
            stack.enter_context(patch.object(run,"screen",return_value=({},[])))
            stack.enter_context(patch.object(run,"rank_all",return_value=([[second],[first]],{})))
            evaluator=stack.enter_context(patch("evaluate.evaluate",side_effect=check_final))
            with redirect_stdout(StringIO()):
                run.study(home,1e-4,1)
            evaluator.assert_called_once()
            self.assertEqual(memories[2009][0]["lessons"],[lesson])


if __name__=="__main__":unittest.main()
