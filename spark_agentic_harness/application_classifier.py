"""Response validation independent of the model's own confidence."""
def validate_decision(paper,reply):
    rows=reply.get('papers',[]) if isinstance(reply,dict) else []
    if not isinstance(rows,list):rows=[]
    matches=[r for r in rows if isinstance(r,dict) and r.get('id')==paper['id']]
    if len(rows)!=1 or len(matches)!=1:
        return {'status':'needs_review','issues':['missing_duplicate_or_extra_decision'],'decision':None}
    decision=matches[0];issues=[]
    enums={'spe_label':{'spe','non_spe','uncertain'},'transfer_route':{'existing_spe','structure_lead','transport_lead','not_supported','manual_review'},
           'carrier':{'lithium','sodium','proton','other','unspecified'}}
    for field,allowed in enums.items():
        if decision.get(field) not in allowed:issues.append('invalid_'+field)
    quote=decision.get('quote')
    if not isinstance(quote,str) or not quote.strip() or not any(quote in (paper.get(k) or '') for k in ['title','abstract']):
        issues.append('quote_not_in_source')
    if not isinstance(decision.get('reason'),str) or not decision['reason'].strip():issues.append('missing_reason')
    if decision.get('spe_label')!='spe' and decision.get('transfer_route')=='existing_spe':issues.append('inconsistent_application_route')
    return {'status':'needs_review' if issues or decision.get('spe_label')=='uncertain' else 'classified_unreviewed',
            'issues':issues,'decision':decision}
