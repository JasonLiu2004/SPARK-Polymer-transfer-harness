import tempfile,unittest,copy
from harness import TemporalHarness
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.calls=[]
  def client(prompt,data):
   self.calls.append(copy.deepcopy(data))
   if 'later_paper' in data:return {'electrolyte_application':True,'structure_match':'similar','mechanism_match':'supported','quote':'ether electrolyte','reason':'fixture'}
   return {'polymer':True,'electrolyte':False,'leads':[{'name':'fixture','structure':'ether','mechanism':'flexible chain','quote':'flexible ether','transfer_hypothesis':'coordination hypothesis','score_reasons':'fixture only','scores':dict(coordination=2,segmental_mobility=2,salt_compatibility=0,structural_feasibility=1)}]}
  self.h=TemporalHarness(self.tmp.name,2015,5,client);self.p={'id':'early','year':2017,'text':'flexible ether','future_label':'secret'}
 def tearDown(self):self.tmp.cleanup()
 def test_pipeline_freeze_and_persistence(self):
  self.h.execute('extract_source',{'paper':self.p});self.assertNotIn('future_label',self.calls[0])
  frozen=copy.deepcopy(self.h.execute('freeze_ranking',{}))
  self.h.execute('validate_later',{'paper':{'id':'later','year':2022,'text':'ether electrolyte'}})
  self.assertEqual(frozen,self.h.state['frozen']);self.assertEqual(len(self.h.execute('report',{})['rows'][0]['later_support']),1)
  self.assertEqual(TemporalHarness(self.tmp.name,2015,5).state['frozen'],frozen)
 def test_time_boundary(self):
  for year in [2014,2020,True]:
   with self.assertRaises(ValueError):self.h.execute('extract_source',{'paper':dict(self.p,year=year)})
 def test_future_gate(self):
  with self.assertRaises(ValueError):self.h.execute('validate_later',{'paper':{'id':'x','year':2020,'text':'x'}})
 def test_frozen_source_gate(self):
  self.h.execute('extract_source',{'paper':self.p});self.h.execute('freeze_ranking',{})
  with self.assertRaises(ValueError):self.h.execute('extract_source',{'paper':self.p})
 def test_quote_gate(self):
  with self.assertRaises(ValueError):self.h.execute('extract_source',{'paper':dict(self.p,text='unrelated')})
 def test_unknown_is_not_negative(self):
  self.h.execute('extract_source',{'paper':self.p});self.h.execute('freeze_ranking',{})
  self.assertEqual(self.h.execute('report',{})['rows'][0]['outcome'],'not_found_in_retrieved_corpus')
if __name__=='__main__':unittest.main()
