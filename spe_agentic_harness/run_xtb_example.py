"""Real GFN2-xTB calculation: dimethyl ether + Li+, not a conductivity test."""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness import ResearchHarness


def example_system():
    # Idealized dimethyl ether starting geometry, subsequently optimized by xTB.
    symbols = ['O']
    positions = [[0., 0., 0.]]
    for sign in (-1, 1):
        carbon = [sign * 1.17, .82, 0.]
        symbols.append('C')
        positions.append(carbon)
        length = math.sqrt(sum(v * v for v in carbon))
        axis = [-v / length for v in carbon]
        perpendicular = [-axis[1], axis[0], 0.]
        for k in range(3):
            angle = k * 2 * math.pi / 3
            vector = [-axis[j] / 3 + math.sqrt(8 / 9) *
                      (math.cos(angle) * perpendicular[j] + math.sin(angle) * (1 if j == 2 else 0))
                      for j in range(3)]
            symbols.append('H')
            positions.append([carbon[j] + 1.09 * vector[j] for j in range(3)])
    return {'fragment': {'symbols': symbols, 'positions_angstrom': positions, 'charge': 0, 'multiplicity': 1},
            'ion': {'symbols': ['Li'], 'positions_angstrom': [[0., -2., 0.]], 'charge': 1, 'multiplicity': 1},
            'input_origin': 'design_hypothesis',
            'sources': ['Constructed C2H6O (dimethyl ether) geometry representing a local ether group; not extracted PEO or a complete electrolyte'],
            'name': 'Dimethyl ether / Li+ gas-phase model'}


def main():
    root = Path(__file__).resolve().parent
    stamp = datetime.now(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')
    output = root / 'outputs' / ('xtb_real_' + stamp)
    h = ResearchHarness(output)
    system = example_system()
    (output / 'input.json').write_text(json.dumps(system, ensure_ascii=False, indent=2), encoding='utf-8')
    result = h.execute('calculate_coordination', {'system': system, 'engine': 'xtb'})
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    data = result.get('data') or {}
    if result['status'] != 'ok' or data.get('status') != 'completed':
        print(json.dumps({'output': str(output), 'result': result}, ensure_ascii=False, indent=2))
        return 2
    energy = data['metrics']['binding_energy']['value']
    distance = min(d['distance_angstrom'] for d in data['li_donor_distances'])
    report = f'''真实 xTB 计算结果
时间：{stamp}（Asia/Shanghai）

调用链：ResearchHarness.execute → calculate_coordination → XTBBackend → 官方 xtb.exe。
引擎：xTB {data['engine_version']}，GFN2-xTB，气相，tight 几何优化。
计算对象：二甲醚 C2H6O 与 Li+，用于演示醚基片段的局部相互作用。
初始几何由脚本构建，不来自文献；这不是完整 PEO/LiTFSI 电解质。

实际执行：中性片段优化、孤立 Li+ 单点计算、复合物优化。
三个计算均正常结束，片段和复合物几何优化达到程序收敛条件。
电子结合能：{energy:.6f} kJ/mol。
定义：E(优化后的复合物) - E(优化后的中性片段) - E(孤立 Li+)。
复合物中最近的 Li–O 距离：{distance:.6f} Å。

总能量（Hartree）：
片段：{data['energies_hartree']['fragment']:.12f}
Li+：{data['energies_hartree']['ion']:.12f}
复合物：{data['energies_hartree']['complex']:.12f}

解释：负结合能表示在这个计算模型下，结合后的电子能低于分离组分。
未包括零点能、热与熵修正，也未做频率检验或构象搜索。
该结果不是结合自由能、实验测量或电导率，不能据此直接排名电解质。

input.json 保存实际输入，result.json 保存返回值、计算来源和记忆 ID。
xtb_calculations 目录保存全部原始 XYZ、命令、stdout.log、stderr.log、优化结构及引擎版本。
状态为 quantum_calculation，不是 test_fixture；结果保持未审阅，eligible_for_ranking=false。
'''
    (output / '真实计算说明.txt').write_text(report, encoding='utf-8')
    print(json.dumps({'output': str(output), 'status': 'completed', 'binding_energy_kJ_mol': energy,
                      'nearest_Li_O_angstrom': distance, 'energies_hartree': data['energies_hartree'],
                      'record_id': data['record_id']}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
