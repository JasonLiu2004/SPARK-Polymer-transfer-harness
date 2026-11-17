import unittest
from transport_extraction import numeric_tokens,assess,validate

class TransportTests(unittest.TestCase):
    def make(self):
        p={'id':'test','doi':None,'abstract':'sigma 1.20 x 10(-4) S/cm at 30 degrees C, activation energy 0.20 eV.'}
        e={'sample':'PEO','material_role':'polymer_electrolyte','sample_association':'explicit','carrier':'lithium','material_state':'dry',
           'sigma':{'value':1.2e-4,'unit':'S/cm','quote':'1.20 x 10(-4) S/cm'},
           'temperature':{'value':30,'unit':'C','quote':'30 degrees C'},
           'energy':{'value':.2,'unit':'eV','kind':'conductivity_activation','model':'arrhenius','quote':'activation energy 0.20 eV'}}
        return p,e
    def test_source_number_and_formula(self):
        p,e=self.make();self.assertEqual(validate(p,e),[])
        self.assertLess(assess(p,e)['target_sigma_S_cm'],1.2e-4)
        e['sigma']['value']=1.2e-3
        self.assertIn('number_not_in_quote_sigma',validate(p,e))
    def test_abstentions(self):
        p,e=self.make();e['temperature']=None
        self.assertEqual(assess(p,e)['target_sigma_S_cm'],None)
        p,e=self.make();e['energy']['model']='vtf'
        self.assertIn('vtf_not_arrhenius',assess(p,e)['issues'])
        e['energy']['model']='arrhenius';e['energy']['kind']='adsorption'
        self.assertIn('wrong_energy_kind',assess(p,e)['issues'])
