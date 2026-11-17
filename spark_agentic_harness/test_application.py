import json
from pathlib import Path
import tempfile
import unittest
from spark_harness import SparkHarness

class Tests(unittest.TestCase):
    def test_labels_hidden_budget_and_memory(self):
        seen=[]
        def client(state):
            seen.append(state)
            return {'papers':[{'id':'p','spe_label':'non_spe','transfer_route':'structure_lead','carrier':'unspecified','quote':'dielectric polymer','reason':'Structural lead only'}]},{}
        with tempfile.TemporaryDirectory() as d:
            catalog=Path(d)/'catalog.json'
            catalog.write_text(json.dumps([{'id':'p','title':'dielectric polymer','abstract':'Flexible films','silver_label':0,'baseline_label':0}]))
            h=SparkHarness(Path(d)/'run',application_catalog=catalog,application_client=client,max_model_calls=1)
            read=h.execute('read_application_paper',{'paper_id':'p'})
            self.assertNotIn('silver_label',str(read))
            r=h.execute('classify_application',{'paper_id':'p'})
            self.assertEqual(r['data']['status'],'classified_unreviewed')
            self.assertEqual(r['data']['decision']['transfer_route'],'structure_lead')
            self.assertNotIn('silver_label',str(seen))
            self.assertEqual(h.execute('classify_application',{'paper_id':'p'})['status'],'error')
            self.assertEqual(h.execute('get_simulation_record',{'record_id':r['data']['record_id']})['status'],'ok')
    def test_fabricated_quote_blocked(self):
        from application_classifier import validate_decision
        r=validate_decision({'id':'p','title':'abc','abstract':'def'}, {'papers':[{'id':'p','spe_label':'spe','transfer_route':'existing_spe','carrier':'lithium','quote':'invented','reason':'x'}]})
        self.assertEqual(r['status'],'needs_review')
