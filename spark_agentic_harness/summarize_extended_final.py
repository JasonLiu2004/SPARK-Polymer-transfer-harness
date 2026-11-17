"""Aggregate completed runs without making an accuracy claim from selected cases."""
import json
from collections import Counter
from pathlib import Path
from summarize_extended import OUT,obj,lines,summarize

def harness(folder):
    events=lines(folder/'execution/events.jsonl')
    a=next((x['data'] for x in reversed(events) if x['tool']=='assess_extracted_transport' and x['status']=='ok'),{})
    trace=lines(folder/'execution/planner_trace.jsonl')
    return {'assessment':a,'model_calls':obj(folder/'complete.json').get('model_calls',obj(folder/'execution/planner_result.json').get('model_calls')),
      'tokens':sum(t.get('usage',{}).get('total_tokens',0) for t in trace)+sum(t.get('data',{}).get('usage',{}).get('total_tokens',0) for t in events if t['status']=='ok')}

if __name__=='__main__':
    base=summarize();pos=[]
    for i in range(1,6):
        folder=OUT/'positive_controls'
        h=harness(folder/f'harness_{i:02}');d=obj(folder/f'direct_{i:02}/direct_result.json')
        pos.append({'index':i,'harness':h,'direct':d})
    trial=[obj(p) for p in sorted((OUT/'policy_trial').glob('*.json')) if p.name!='manifest.json']
    case=harness(OUT/'case_study')
    result={'batch_tasks':60,'batch_unique_papers':30,'additional_fulltext_cases':1,
      'boundary':base['aggregate'],'positive_controls':pos,'repeats':base['repeats'],
      'policy_trial':{'n':len(trial),'status':dict(Counter(x.get('assessment',{}).get('status','error') for x in trial)),
        'evidence_issue_cases':sum(bool(x.get('evidence_issues')) for x in trial),
        'tokens':sum(x.get('usage',{}).get('total_tokens',0) for x in trial),
        'promotion':'not_promoted','independent_test':False},'case_study':case}
    (OUT/'final_summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    report='''扩展实验与全文案例（2026-11-17）

一、实际完成量
60个批量任务：20篇新增边界文献×Harness与直接LLM两种方法=40；原有5篇可计算文献重新自动抽取×两种方法=10；原10例重复执行=10。批量共30篇不同文献。
另完成1篇独立全文案例，以及25次抽取策略复测。合计31篇不同文献；任务数、模型调用数、论文数分别统计。
上述均为真实deepseek-flash调用。批量是本地WoS题名/摘要，案例是本地PDF；本轮没有新增在线检索、分子动力学或湿实验。

二、方法对照
20篇边界样例：Harness与直接LLM均20/20返回“待补输入”，原文引用/数值格式校验均无报错。样例涉及缺温度/缺Ea、不同样品关联、陶瓷与复合材料数值归属、VTF及能量类型等问题。这是有目的的边界测试，不能据此宣称总体准确率或Harness优于直接LLM。
Harness使用161次模型调用、440801 tokens；直接LLM使用20次、59445 tokens，约7.42倍token开销。两种方法成本未对齐。
5篇可计算正例：原Harness自动抽取后4篇进入计算、1篇因材料归属被阻止；直接LLM给出5个数值。C05直接LLM将材料标为other后仍计算，体现直接回答和判定规则存在不一致；复合电解质本身应在本任务范围内，需修正范围定义。
原10例重复执行：性质状态与数值10/10一致；分类三个字段9/10一致。C05的SPE分类发生变化，进一步定位到陶瓷主导复合材料的范围边界。
20篇中第2篇含不同加工方法对应的多个样品，两种方法都选择了缺完整参数的样品，因此“与助手预先参考19/20一致”不是可报告的抽取准确率。后续基准应按具体样品标注，而非每篇只预设一个答案。

三、策略修订的影子测试
仅明确：含离子传导聚合物相的聚合物/陶瓷复合电解质属于目标范围，即使陶瓷主导质量占比或传导路径。复合物数值必须保留复合物归属。
同25篇重新调用抽取器：5/5正例可计算，20/20边界样例仍待补输入，引用/数值格式校验0例报错。C05在25℃的工具估计为4.6563×10^-5 S/cm。
这是观察失败后由助手提出修改、在开发集进行的策略验证；尚未替换默认提示，尚无独立测试集。可作为RSI接口的实例，不是自主递归自我改进的实验结论。下一步需冻结未见测试集、成本预算和回退条件，验证后再决定是否发布策略。

四、具体case study：ZIF-67@CF/PEO-SN
论文：Three-Dimensional Metal–Organic Framework@Cellulose Skeleton-Reinforced Composite Polymer Electrolyte for All-Solid-State Lithium Metal Battery，ACS Nano 2024，DOI 10.1021/acsnano.4c01257。
目标：判断25℃传导能力并设计与PEO、ZIF-67@CF/PEO的对比验证。
真实执行：读取摘要→分类→抽取→发现缺Ea→搜索本地全文→读取PDF第7、8页→重新抽取→工具换算→搜索Table S1→形成建议。共13个规划步骤、16次模型调用、11次工具调用，保留全部日志与SQLite证据记录；本案例未实际调用记忆回读工具。
摘要给出30℃电导率1.17×10^-4 S/cm，全文第7页补充该样品表观活化能0.45 eV。工具按局部Arrhenius假设换算到25℃，约8.76×10^-5 S/cm，较1×10^-4参考线低约12.4%。这只是温度换算估计，不能作为原文实测或独立模拟结果。
原论文已在25、30、40、50、60℃测量，精确值指向Table S1。本地只有主文，故下一步优先取得SI表值或复测25℃EIS，而不是把温度换算当作新发现。

原文第7页三样品对比（30℃）：
PEO：σ=1.72×10^-5 S/cm，Ea=0.87 eV，tLi+=0.14。
ZIF-67@CF/PEO：σ=1.81×10^-5 S/cm，Ea=0.82 eV，tLi+=0.38。
ZIF-67@CF/PEO-SN：σ=1.17×10^-4 S/cm，Ea=0.45 eV，tLi+=0.40。
SN增塑使相对无SN增强体系的电导率提高约6.46倍；抗拉强度19.97→18.66 MPa，下降约6.6%；杨氏模量375.92→295.85 MPa，下降约21.3%。因此推荐要同时权衡传导与力学，保留“含SN增塑”的材料状态。
建议实验：固定盐配比、膜厚和电极几何，比较三种体系的25℃EIS、迁移数、力学及Li对称电池界面稳定性；先核对Table S1与本文配方，不直接据单一电导率推荐为最优材料。

五、与原文工作的关系
原任务复现：已有同数据与时间划分的分类器独立重建，测试1943篇，F1=0.9505；原SPARK排名结果仍来自归档读取。
本轮新增：自动性质抽取、证据校验、工具温度换算、规划器按缺口检索全文、直接LLM对照、重复性检查和范围策略影子测试。没有重新训练原世界模型，也没有运行分子动力学求扩散系数。

六、结果位置
final_summary.json：总体汇总；comparison.json：20篇逐例对照。
positive_controls：5篇自动抽取正例；repeat_XX：10例重复日志。
policy_trial：25次策略复测和策略哈希；默认策略未修改。
case_study：PDF页文本与哈希、全文运行日志、SQLite记忆、模型原始recommendation.txt。
各execution目录保留events.jsonl、planner_trace.jsonl、planner_result.json。首次目录初始化错误在调用API前发生，已修复并保留initial_failure.json，不计为科学实验结果。
'''
    (OUT/'扩展实验与案例解读.txt').write_text(report,encoding='utf-8')
    print(json.dumps({'tasks':60,'policy':result['policy_trial'],'case':case['assessment'].get('target_sigma_S_cm')},ensure_ascii=False))
