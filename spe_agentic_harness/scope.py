"""Auditable metadata gate for polymer-electrolyte literature discovery."""
import re


def restore_abstract(index):
    if not isinstance(index, dict):
        return ''
    words = [(position, word) for word, positions in index.items() for position in positions]
    return ' '.join(word for _, word in sorted(words))


def screen(paper, config):
    text = ' '.join([paper.get('title') or '', paper.get('abstract') or '']).lower()
    text = re.sub(r'[-–—]', ' ', text)
    hits = {}
    for group in ('polymer_terms', 'transport_terms', 'structural_terms', 'battery_terms', 'conditional_terms'):
        hits[group] = [term for term in config.get(group, []) if term.lower().replace('-', ' ') in text]
    route = None
    if paper.get('type') in config['exclude_types']:
        decision, reason = 'background', 'Review/editorial: retained as background, not a discovery candidate'
    elif hits['polymer_terms'] and hits['transport_terms']:
        decision, reason = 'include', 'Polymer system and ionic-transport evidence both present in metadata'
        route = 'transport_evidence'
    elif hits['polymer_terms'] and hits['structural_terms']:
        decision, reason = 'include', 'Polymer structure/property lead; electrolyte transfer remains a hypothesis'
        route = 'structure_hypothesis'
    elif not paper.get('abstract') or hits['polymer_terms']:
        decision, reason = 'manual_review', 'Scope evidence is insufficient; keyword absence does not establish irrelevance'
    else:
        decision, reason = 'exclude', 'No polymer-system signal in available metadata'
    return {'decision': decision, 'reason': reason, 'matched_terms': hits,
            'inclusion_route': route, 'suitability': 'not_assessed',
            'category': 'existing_battery_context' if hits['battery_terms'] else 'cross_domain_lead',
            'transfer_checks': ['carrier identity', 'water/solvent content', 'salt loading',
                                'measurement temperature', 'solid film formation',
                                'electronic vs ionic conductivity', 'prior battery applications'],
            'novelty': 'not_assessed'}
