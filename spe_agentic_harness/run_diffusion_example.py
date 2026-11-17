"""Run a real 100 ps MD benchmark through the agent's registered tool."""
from datetime import datetime
import json
from pathlib import Path
from harness import ResearchHarness


def write_report(output, result):
    data = result.get('data', {})
    if data.get('status') != 'completed':
        return
    lines = ['OpenMM 真实扩散计算测试', '',
             '调用：ResearchHarness.execute → run_diffusion_benchmark → 独立 Python → OpenMM → MSD 拟合。',
             f"引擎：OpenMM {data['engine_version']}；体系：LiCl 水溶液；温度：300 K。",
             f"原子数：{data['atom_count']}；实际盐浓度：{data['actual_salt_concentration_mol_L']:.4f} mol/L。",
             f"平衡：20 ps；生产：{data['production_ps']} ps；步长：0.002 ps；采样间隔：0.1 ps。", '']
    for symbol, metric in data['metrics'].items():
        lines.append(f"{symbol}：{metric['ion_count']} 个离子，初步 D={metric['preliminary_D_m2_s']} m²/s；"
                     f"拟合区间 {metric['fit_window_ps']} ps；R²={metric['r_squared']}；log–log 指数={metric['log_log_exponent']}。")
    lines += ['', '公式：D = MSD 对时间斜率 / 6；先算 nm²/ps，再乘 1e-6 转成 m²/s。',
              '这些是实际分子动力学轨迹的分析结果，不是 LLM 生成值或手工输入的扩散系数。',
              '本次为水溶液计算链路验证，不是固态聚合物电解质性能预测。单次短轨迹未确认收敛，不能用于材料排名。',
              'accepted_D_m2_s=null，converged=false，eligible_for_ranking=false。',
              f"记忆记录 ID：{data.get('record_id')}", f"原始文件：{data['artifact_dir']}"]
    (output/'结果说明.txt').write_text('\n'.join(lines), encoding='utf-8')
    try:
        import matplotlib
    except ImportError:
        return
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    fig, ax = plt.subplots(figsize=(7, 4.5))
    for symbol, metric in data['metrics'].items():
        curve = np.loadtxt(Path(data['artifact_dir'])/f'msd_{symbol}.csv', delimiter=',', skiprows=1)
        line, = ax.plot(curve[:, 0], curve[:, 1], label=f'{symbol}: time-origin averaged MSD')
        x = np.asarray(metric['fit_window_ps'])
        ax.plot(x, metric['slope_nm2_ps']*x+metric['intercept_nm2'], '--', color=line.get_color())
    ax.set(xlabel='Lag time (ps)', ylabel='MSD (nm$^2$)',
           title='LiCl(aq), 300 K: short MD benchmark\nDashed: fitted window; convergence not established')
    ax.legend()
    fig.tight_layout()
    fig.savefig(output/'msd.png', dpi=180)
    plt.close(fig)


if __name__ == '__main__':
    output = Path(__file__).resolve().parent/'outputs'/('diffusion_real_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    h = ResearchHarness(output)
    print(str(output), flush=True)
    result = h.execute('run_diffusion_benchmark', {'production_ps': 100, 'seed': 2026})
    (output/'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    write_report(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get('data', {}).get('status') == 'completed' else 1)
