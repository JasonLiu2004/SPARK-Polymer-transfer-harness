"""Small offline demonstration: real validation/arithmetic + labelled fixture I/O.

No LLM, network, MD or quantum chemistry is invoked. Artificial backend lives in
test_simulation.py and is explicitly injected only into the fixture run.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness import ResearchHarness
from test_simulation import FixtureBackend, candidate, assumptions, coordination_system


def main():
    root = Path(__file__).resolve().parent
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')
    output = root / 'outputs' / ('simulation_smoke_' + stamp)
    output.mkdir(parents=True)
    evidence = {'test_type': 'offline interfaces; no real MD/QM or LLM', 'checks': {}}
    h = ResearchHarness(output / 'without_backend')
    incomplete = h.execute('prepare_simulation_input', {'candidate': candidate()})
    assert incomplete['data']['status'] == 'needs_input'
    evidence['checks']['missing_fields'] = incomplete
    prepared = h.execute('prepare_simulation_input', {'candidate': candidate(), 'assumptions': assumptions()})
    assert prepared['data']['status'] == 'schema_ready'
    evidence['checks']['prepared_with_assumptions'] = prepared
    absent = h.execute('simulate_electrolyte', {'prepared_id': prepared['data']['record_id'], 'engine': 'pemd'})
    assert absent['data']['status'] == 'unavailable'
    evidence['checks']['unconnected_backend'] = absent
    ne_request = json.loads((root / 'examples' / 'transport_example.json').read_text(encoding='utf-8'))
    ne = h.execute('predict_conductivity', ne_request)
    assert ne['data']['status'] == 'completed'
    evidence['checks']['real_formula_synthetic_inputs'] = ne

    fake = ResearchHarness(output / 'fixture_backend', simulation_provider=FixtureBackend())
    p = fake.execute('prepare_simulation_input', {'candidate': candidate(), 'assumptions': assumptions()})['data']
    sim = fake.execute('simulate_electrolyte', {'prepared_id': p['record_id'], 'engine': 'pemd'})
    analysis = fake.execute('analyze_ion_transport', {'simulation_id': sim['data']['record_id'], 'engine': 'seamm'})
    coordination = fake.execute('calculate_coordination', {'system': coordination_system(), 'engine': 'xtb'})
    polymer = fake.execute('calculate_polymer_properties', {'prepared_id': p['record_id'], 'engine': 'radonpy', 'properties': ['density']})
    for name, result in [('fixture_simulation', sim), ('fixture_analysis', analysis),
                         ('fixture_coordination', coordination), ('fixture_polymer_property', polymer)]:
        assert result['data']['status'] == 'completed'
        assert result['data']['data_origin'] == 'test_fixture'
        assert result['data']['eligible_for_ranking'] is False
        evidence['checks'][name] = result
    saved = fake.execute('get_simulation_record', {'record_id': analysis['data']['record_id']})
    assert saved['data']['parent_id'] == sim['data']['record_id']
    evidence['checks']['memory_retrieval'] = saved
    (output / 'results.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    report = f'''计算工具接口小测试
测试时间：{stamp}（Asia/Shanghai）

本次运行不调用 LLM、网络、真实 MD 或量子化学引擎。

实际执行的功能
1. 缺失检查：初始候选缺少 {', '.join(incomplete['data']['missing'])}。
2. 显式补充 5 项建模假设后，状态为 schema_ready。化学结构尚未验证。
3. 未连接计算服务时，模拟工具返回 unavailable，不返回虚构的模拟结果。
4. Nernst–Einstein 公式计算完成，得到 {ne['data']['conductivity']['value']:.8g} S/cm。
   这是人工扩散系数输入的算术结果，不是 PEO/LiTFSI 的预测或实测值。

测试后端验证的接口
5. 输入记录 → 模拟接口 → 输运分析 → 记忆查询：通过。
6. 局部配位计算接口：通过。
7. 聚合物辅助性质接口：通过。
上述测试后端只返回预设的人工数据，没有执行 PEMD、SEAMM、xTB 或 RadonPy。
结果均标为 test_fixture，eligible_for_ranking=false，不能作为论文中的材料性能结果。

文件
results.json：完整请求、返回状态、来源和记录 ID。
without_backend/events.jsonl：真实校验与公式计算调用轨迹。
fixture_backend/events.jsonl：测试后端调用轨迹。
两个运行目录各自保存 knowledge.sqlite，避免混淆人工测试记录与实际研究记忆。

完成范围
已实现 agent 工具定义、输入准备、直接结果接口、结果校验与持久化。
远程计算服务尚未部署或接通，未测真实模拟耗时及数值准确性。
'''
    (output / '测试说明.txt').write_text(report, encoding='utf-8')
    print(json.dumps({'output': str(output), 'checks': len(evidence['checks']), 'status': 'passed'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
