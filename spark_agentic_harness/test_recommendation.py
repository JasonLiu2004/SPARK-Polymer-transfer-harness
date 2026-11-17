import json
import unittest
from run_recommendation_demo import project, PAPER, CATALOG


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.paper=next(x for x in json.loads(CATALOG.read_text(encoding='utf-8')) if x['id']==PAPER)

    def test_reference_temperature_and_cooling(self):
        for row in project(self.paper,303.15)['rows']:
            self.assertEqual(row['projected_sigma_S_cm'],row['measured_sigma_S_cm'])
        cooled=project(self.paper,298.15)['rows']
        self.assertAlmostEqual(cooled[0]['projected_sigma_S_cm'],3.3002883e-5,places=12)
        self.assertLess(cooled[1]['projected_sigma_S_cm'],cooled[1]['measured_sigma_S_cm'])

    def test_refuses_missing_evidence_and_extrapolation(self):
        with self.assertRaises(ValueError):project({**self.paper,'abstract':''},298.15)
        for t in [0,400,float('nan'),True]:
            with self.assertRaises(ValueError):project(self.paper,t)
