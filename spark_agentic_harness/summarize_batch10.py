import json
from pathlib import Path
from run_batch10 import OUT

def read_lines(path):
    return [json.loads(x) for x in path.read_text(encoding='utf-8').splitlines() if x.strip()] if path.exists() else []

def main():
    rows=[];calls=0;tokens=0;format_errors=0;tool_errors=0
    cases=json.loads((OUT/'cases.json').read_text(encoding='utf-8'))
    for c in cases:
        folder=OUT/c['case_id'];result_path=folder/'planner_result.json'
        if not result_path.exists():continue
        result=json.loads(result_path.read_text(encoding='utf-8'))
        trace=read_lines(folder/'planner_trace.jsonl');events=read_lines(folder/'events.jsonl')
        props=[e['data'] for e in events if e['tool']=='assess_temperature_property' and e['status']=='ok']
        classifications=[e['data'] for e in events if e['tool']=='classify_application' and e['status']=='ok']
        prop=props[-1] if props else {}
        retrieved=any(e['tool']=='get_simulation_record' and e['status']=='ok' and e.get('data',{}).get('record_id')==prop.get('record_id') for e in events)
        errors=sum(1 for e in trace if 'parse_error' in e.get('decision',{}) or e.get('observation',{}).get('error')=='Return a valid action object')
        n_tokens=sum(e.get('usage',{}).get('total_tokens',0) for e in trace)+sum(e['data'].get('usage',{}).get('total_tokens',0) for e in events if e['tool']=='classify_application' and e['status']=='ok')
        calls+=result['model_calls'];tokens+=n_tokens;format_errors+=errors
        tool_errors+=sum(e['status']=='error' for e in events)
        rows.append({**c,'planner_status':result['status'],'model_calls':result['model_calls'],
          'steps':result['steps'],'tool_calls':result['tool_calls'],'tokens':n_tokens,'format_errors':errors,
          'property':prop,'classification':classifications[-1] if classifications else None,
          'memory_retrieved':retrieved,'answer':result['answer'],
          'trajectory':[e.get('decision',{}).get('action',{}).get('tool','invalid_format') for e in trace]})
    from collections import Counter
    summary={'n':len(rows),'finished':sum(r['planner_status']=='finished' for r in rows),
       'property_status_counts':dict(Counter(r['property'].get('status','not_called') for r in rows)),
       'classified':sum(bool(r['classification']) for r in rows),'memory_retrieved':sum(r['memory_retrieved'] for r in rows),
       'model_calls':calls,'reported_tokens':tokens,'format_errors':format_errors,'tool_errors':tool_errors,
       'classification_status_counts':dict(Counter((r['classification'] or {}).get('status','not_called') for r in rows)),
       'sampling':'purposive 10-paper demonstration; curated property inputs, no accuracy claim',
       'assistant_review_notes':[
         'C05: classifier calls ceramic-dominant PEO composite non_spe/structure_lead. The abstract explicitly describes a polymer/ceramic composite electrolyte; this boundary decision requires review, not scientific acceptance.',
         'C01: the reported numeric conductivity is attributed to SIPE in the abstract; do not automatically transfer it to the later D-SIPE dual-salt formulation without full-text sample matching.',
         'All projected values assume local Arrhenius applicability. Numerical execution is verified; phase/solvent effects and independent experimental accuracy are not.'
       ],'rows':rows}
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['10篇文献自主规划与推荐实验',
      f'完成 {summary["finished"]}/{len(rows)}；模型调用 {calls}；报告token {tokens}；格式错误 {format_errors}。',
      '这是有目的选择的工具链演示。性质输入由助手从摘要转录并核对，工具按固定规则拒绝不充分输入。',
      'LLM负责调用工具、解释返回值与建议实验。未接入新结构预测模型或真实聚合物MD。',
      '独立分类、性质校验与最终推荐是不同验收层级。引用匹配不是科学正确性的充分证明。',
      '助手复核：C05将陶瓷主导的聚合物/陶瓷复合电解质判为non_spe，分类边界需复核；下列保留模型原始建议，不能作为该判断正确的背书。',
      '助手复核：C01数值对应摘要中的SIPE，后文D-SIPE双盐配方需全文匹配后才能共用性能值。','']
    for r in rows:
        lines.extend([r['case_id']+' '+r['name'],'DOI: '+str(r['doi']),
          '运行：'+r['planner_status']+'；性质：'+r['property'].get('status','not_called'),
          '动作：'+' → '.join(r['trajectory']),r['answer'],''])
    (OUT/'全部样例与总结.txt').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k!='rows'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
