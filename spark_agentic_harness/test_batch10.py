import json
import unittest
from run_batch10 import OUT,calculate

class Batch10Tests(unittest.TestCase):
    def setUp(self):
        self.cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'))
        self.papers={p['id']:p for p in json.loads((OUT/'catalog.json').read_text(encoding='utf-8'))}
    def test_supported_and_missing_inputs(self):
        results=[calculate(c,self.papers[c['paper_id']],298.15) for c in self.cases]
        self.assertEqual([r['status'] for r in results],['computed_unreviewed']*5+['measured_at_target']+['needs_input']*4)
        self.assertTrue(all(r['projected_sigma_S_cm'] is None for r in results[5:]))
    def test_identity_and_source_integrity(self):
        c=self.cases[0];p=self.papers[c['paper_id']]
        with self.assertRaises(ValueError):calculate(c,{**p,'abstract':p['abstract']+' modified'},298.15)
        with self.assertRaises(ValueError):calculate(c,self.papers[self.cases[1]['paper_id']],298.15)
    def test_temperature_bound_and_identity(self):
        c=self.cases[0];p=self.papers[c['paper_id']]
        self.assertEqual(calculate(c,p,303.15)['target_sigma_S_cm'],c['sigma_S_cm'])
        self.assertEqual(calculate(c,p,320)['status'],'needs_input')
        for t in [True,float('nan'),0]:
            with self.assertRaises(ValueError):calculate(c,p,t)
