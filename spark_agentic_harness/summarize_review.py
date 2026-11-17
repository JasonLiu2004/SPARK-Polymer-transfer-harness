"""Readable review report derived from saved results, without altering predictions."""
import hashlib
import json
from build_review_benchmark import OUT

if __name__=='__main__':
    evaluation=OUT/'eval_111504'; retest=OUT/'abstention_8192_111858'
    scores=json.loads((evaluation/'extraction_scores.json').read_text(encoding='utf-8'))
    reviewed=json.loads((OUT/'reviewed_records.json').read_text(encoding='utf-8'))
    lines=['复核与小型评测结果（2026-11-17）','',
           '一、原7条记录复核',
           '以PDF文本和渲染页面复核；复核者为本助手，尚未经过独立领域专家核验。',
           '7个电导率数值、配方分组和温度对应关系与正文相符。R4-R7的sample引文移到PDF第5页的准确措辞，4项引用错误修正为0项。原始结果未覆盖。',
           '制备溶剂是DMF/acetone；正文第9页明确讨论残留溶剂，主要为DMF，对电导率有贡献。不能当成无溶剂SPE。',
           '第5页盐比例筛选与第9页BN比较给出不同无BN基线；保持独立测量上下文，不平均、不合并。',
           '室温约21℃来自方法部分，100℃记录单独保留。第10页老化结果不在这7条中，本次不是穷尽抽取。','',
           '记录 | 样品 | 温度℃ | 电导率S/cm | 测量段落']
    for i,r in enumerate(reviewed['records']):
        lines.append(f"{r['id']} | {r['sample']['value']} | {r['temperature']['value']} | {r['conductivity']['value']:.6g} | PDF p{5 if i<3 else 9}")
    lines+=['','二、5篇论文、11条指定记录的页级抽取测试',
            '参考集先冻结，再调用现有 deepseek-flash API；参考答案没有传入模型。提供指定样品和证据页，测数值、单位、温度缺失与引用保真，不测整篇自动检索召回率。',
            'BN论文7条，另外4篇各1条。包括一个目标材料电导率未在所给页出现的负例，两个未给数值温度的样例，以及mS/cm到S/cm的换算。']
    for k,v in scores['totals'].items():lines.append(f'{k}: {v}/{scores["denominator"]}')
    lines+=['10个非空电导率与1个缺失值判断正确；8个数值温度与3个缺失数值温度判断正确。',
            'P5引用失败原因：PDF侧栏水印“31,to”混入正文行，模型输出了清理后的句子，不再是原始页文本的逐字子串。数字正确，但引用检查仍判失败，不追溯修改成绩。',
            '该开发集由助手建立，样本量小、条件已给定、部分样本来自已检查材料；不能声称100%全文抽取准确率或推广性能。','',
            '三、弃权与来源边界：6种情景×3轮']
    groups=[('4096-token 原测试',[evaluation/f'abstention_{i}.json' for i in range(3)]),
            ('8192-token 对照复测',[retest/f'repeat_{i}.json' for i in range(3)])]
    for name,files in groups:
        rows=[json.loads(f.read_text(encoding='utf-8')) for f in files if f.exists()]
        valid=sum(isinstance(r.get('reply',{}).get('decisions'),list) for r in rows)
        passed=sum(c['pass'] for r in rows for c in r['checks'])
        lines.append(f'{name}：已完成{len(rows)}轮；有效JSON决策{valid}轮；规则匹配{passed}/{6*len(rows)}。')
    lines+=['4096-token测试中3次全部返回空内容，usage显示4096 completion tokens全为reasoning tokens。记为接口无有效输出，不解释成18次语义误判。',
            '8192预算仅1/3轮返回有效JSON；有效轮与冻结动作标签严格匹配4/6。另2项（短MD、残留DMF）选择quarantine_for_review，而参考标签是retain_and_seek_evidence。这是更保守的处置，不是宣称可直接排名的科学错误；原严格成绩保持不变。',
            '该有效轮没有把缺失值当零、没有忽略弃权、没有把含残留DMF称为干态SPE，并能读取其他seed归档。但两轮仍无输出，所以不能宣称总控稳定性通过。',
            '对照仅提高输出预算，保持问题和提示词一致。情景为：预测弃权、缺失电导率、短程水溶液MD、残留DMF、证据引用失败、无权重但已有其他种子归档。',
            '这是提示中已规定规则的组件级遵循测试，不是自主规划成功率、临床/实验安全保证或正式RSI改进证据。','',
            '四、文件',
            'reviewed_records.json：原7条的修订版本、引用修改清单、残留溶剂和上下文说明。',
            'review_memory.sqlite / review_memory_receipt.json：独立复核快照，未覆盖原知识。断言仍保留unreviewed_extraction状态，未自动升级为专家验证事实。',
            'cases.json / reference.json：固定输入、PDF SHA256及参考答案。',
            'eval_111504：5篇原始模型输出、逐项分数、4096预算行为测试。',
            'abstention_8192_111858：同题8192预算对照。','',
            '结论：已拿到可追溯的数值抽取与引用复核结果；下一步优先做全文自主取证、干扰引文/多温度/老化条件的盲测，并由领域研究者复核标注。']
    (OUT/'复核与评测报告.txt').write_text('\n'.join(lines),encoding='utf-8')
    manifest={f:hashlib.sha256((OUT/f).read_bytes()).hexdigest() for f in ['cases.json','reference.json','reviewed_records.json']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('\n'.join(lines[17:28]))
