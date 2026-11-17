import tempfile
import unittest
from spark_harness import SparkHarness

class Tests(unittest.TestCase):
    def test_source_preserving_screen(self):
        with tempfile.TemporaryDirectory() as d:
            h=SparkHarness(d)
            original={'id':'paper1','title':'Polymer electrolytes: a review','abstract':'Polymer ionic conductivity','type':'article'}
            h.search_papers['paper1']=original.copy()
            r=h.execute('spark_screen_search',{'paper_ids':['paper1']})
            p=r['data']['papers'][0]
            self.assertEqual(p['screening']['decision'],'background')
            self.assertEqual(p['abstract'],original['abstract'])
            self.assertNotIn('screening',h.search_papers['paper1'])
            self.assertEqual(h.execute('spark_screen_search',{'paper_ids':['unseen']})['status'],'error')
    def test_archive_and_memory(self):
        with tempfile.TemporaryDirectory() as d:
            h=SparkHarness(d)
            r=h.execute('spark_candidates',{'seed':20260814,'limit':1})
            self.assertEqual(r['status'],'ok')
            self.assertEqual(r['data']['payload']['panel_count'],258)
            self.assertEqual(r['data']['payload']['rows'][0]['r42_rank'],1)
            saved=h.execute('get_simulation_record',{'record_id':r['data']['record_id']})
            self.assertEqual(saved['data']['source_sha256'],r['data']['source_sha256'])
            self.assertEqual(h.execute('spark_candidates',{'seed':1})['status'],'error')
    def test_budget(self):
        with tempfile.TemporaryDirectory() as d:
            h=SparkHarness(d,max_tool_calls=1)
            self.assertEqual(h.execute('spark_capabilities',{})['status'],'ok')
            self.assertEqual(h.execute('spark_summary',{})['status'],'error')
