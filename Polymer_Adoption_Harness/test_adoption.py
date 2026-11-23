import unittest
from adoption import admit,learn,ranked,seed
from controller import arguments
from graph import AXES,CUES
from results import average_precision


CUT=2004
THRESHOLD=1.e-4


def formulation(name,sigma,year=1999,temp=25,recipe="r1",status="predicted"):
    return {"material":name,"recipe":recipe,"sigma_S_cm":sigma,"temperature_C":temp,"source_year":year,
            "source_doi":"10.0000/fixture","status":status,"salt_wt_pct":20}


def judgment(v=0):
    return {"vote":v,"role":"host","reason":"unit fixture","doi":""}


class TestAdmission(unittest.TestCase):
    def test_union_at_threshold_deduplicates_qualifying_recipes(self):
        r=formulation("A",THRESHOLD,temp=60)
        candidates=admit(["B","C"],{"A":[r,r,formulation("A",0.00002,recipe="r2")],
            "B":[formulation("B",0.0002)],"C":[formulation("C",None,status="failed")]},CUT)
        self.assertEqual({n:e["route"] for n,e in candidates.items()},{"A":"hpg_only","B":"both","C":"paper_only"})
        self.assertEqual(candidates["A"]["temperatures_C"],[60])
        self.assertEqual(len(candidates["A"]["qualifying_recipes"]),1)

    def test_nonfinite_absent_future_and_wrong_temperature(self):
        preds={n:[formulation(n,v,yr,t)] for n,v,yr,t in
                [("future",0.1,2005,25),("nan",float("nan"),2000,25),("inf",float("inf"),2000,60),
                 ("missing",None,2000,25),("impossible",0.1,2000,-300),("below",0.0000999,2000,25)]}
        preds["no_doi"]=[{**formulation("no_doi",0.1),"source_doi":""}]
        preds["unconverted_units"]=[{**formulation("unconverted_units",0.1),"unit":"mS/cm"}]
        self.assertEqual(admit([],preds,CUT),{})
        for v in (0.,-1.,float("nan")):
            with self.assertRaises(ValueError):admit([],{},CUT,v)

    def test_future_valid_design_at_a_different_temperature_suffices(self):
        for t in (0,30,37.5,75):
            pool=admit([],{"A":[formulation("A",THRESHOLD,temp=t)]},CUT)
            self.assertEqual(pool["A"]["route"],"hpg_only")
            self.assertEqual(pool["A"]["temperatures_C"],[t])

    def test_cannot_override_qualified_repeat_or_new_candidate(self):
        p={"papers":1,"latest":2000,"cues":dict.fromkeys(CUES,0),"axes":dict.fromkeys(AXES,[])}
        panel={"A":p,"B":p,"C":p}
        physics={k:[formulation(k,0.001)] for k in ("A","B")}
        rows=ranked(panel,{k:judgment(-2) for k in panel},{k:judgment(-2) for k in physics},physics,
             {"A":[{"doi":"past"}]},seed(CUT),CUT,THRESHOLD)
        self.assertEqual({k for k,r in rows.items() if r["in_pool"]},{"A","B"})
        self.assertEqual(rows["A"]["stratum"],"repeat")
        self.assertEqual(rows["B"]["stratum"],"first_observed")
        self.assertEqual({rows["A"]["pool_rank"],rows["B"]["pool_rank"]},{1,2})

    def test_training_preserves_features_for_both_abstentions(self):
        x=[0.]*10
        entries={"A":{"features":[.8,*x[1:]],"rank":2,"paper_vote":0,"stratum":"first_observed","in_pool":False},
                 "B":{"features":[.1,*x[1:]],"rank":1,"paper_vote":0,"stratum":"first_observed","in_pool":False}}
        after,pairs=learn({"rankings":entries},{"A":[{"role":"host"}]},seed(CUT),2009)
        self.assertTrue(pairs[0]["previous_zero"])
        self.assertNotEqual(after["weights"][0],0)
        self.assertEqual(after["through"],2009)
        self.assertEqual(entries["A"]["paper_vote"],0)

    def test_tie_aware_ap(self):
        self.assertEqual(average_precision({"A":{"s":1},"B":{"s":1}},{"A"},"s"),0.75)
        self.assertIsNone(average_precision({"A":{"s":1}},set(),"s"))

    def test_native_tool_payloads(self):
        expected={"remaining":"hold","items":[]}
        self.assertEqual(arguments({"arguments":'{"remaining":"hold","items":[]}'}),expected)
        self.assertEqual(arguments(expected),expected)


if __name__=="__main__":unittest.main()
