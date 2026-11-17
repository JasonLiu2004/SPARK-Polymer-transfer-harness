"""Real OpenMM benchmark and multi-origin Einstein self-diffusion analysis."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parent
MD_PYTHON = ROOT / '.runtime' / 'python311' / 'python.exe'
RUNTIME = ROOT / '.runtime' / 'md_env' / 'Lib' / 'site-packages'
BACKEND_BLOCKED_REASON = None if MD_PYTHON.is_file() else 'Isolated MD Python runtime is not installed'


def analyze(positions_nm, interval_ps):
    """Continuous, unwrapped coordinates; average over particles and time origins.

    No species COM subtraction: that would erase a single ion's diffusion.
    Fitting overlapping time origins does not provide independent error bars.
    """
    p = np.asarray(positions_nm, dtype=float)
    if p.ndim != 3 or p.shape[2] != 3 or p.shape[0] < 40 or p.shape[1] < 1:
        raise ValueError('Need >=40 frames, >=1 ion, three Cartesian coordinates')
    if not np.isfinite(p).all() or not np.isfinite(interval_ps) or interval_ps <= 0:
        raise ValueError('Non-finite trajectory or invalid sampling interval')
    lags = np.arange(1, len(p)//2 + 1)
    times = lags * interval_ps
    msd = np.array([np.mean(np.sum((p[k:] - p[:-k])**2, axis=2)) for k in lags])
    # Long enough to omit the earliest inertial regime, retain many time origins.
    mask = (times >= times[-1]*0.2) & (times <= times[-1]*0.8)
    x, y = times[mask], msd[mask]
    slope, intercept = np.polyfit(x, y, 1)
    denom = np.sum((y-y.mean())**2)
    r2 = float(1-np.sum((y-(slope*x+intercept))**2)/denom) if denom > 0 else None
    alpha = float(np.polyfit(np.log(x), np.log(y), 1)[0]) if np.all(y > 0) else None
    # nm^2/ps -> m^2/s = 1e-6. Three-dimensional Einstein denominator is 6.
    d = float(slope / 6 * 1e-6) if slope > 0 else None
    return {'preliminary_D_m2_s': d, 'accepted_D_m2_s': None,
            'fit_window_ps': [float(x[0]), float(x[-1])], 'slope_nm2_ps': float(slope),
            'intercept_nm2': float(intercept), 'r_squared': r2, 'log_log_exponent': alpha,
            'diffusive_window_heuristic': bool(d and r2 is not None and r2 > .95 and alpha is not None and .8 < alpha < 1.2),
            'quality': 'unvalidated_short_single_replica',
            'lag_ps': times.tolist(), 'msd_nm2': msd.tolist()}


def run_benchmark(output, production_ps=100, seed=2026):
    if type(production_ps) is not int or not 20 <= production_ps <= 500:
        raise ValueError('production_ps must be an integer in [20,500]')
    if type(seed) is not int or not 1 <= seed <= 2147483647:
        raise ValueError('seed must be an integer in [1,2147483647]')
    if BACKEND_BLOCKED_REASON:
        return {'status': 'unavailable', 'error_category': 'native_runtime_incompatible',
                'reason': BACKEND_BLOCKED_REASON}
    if not (RUNTIME / 'openmm').is_dir():
        return {'status': 'unavailable', 'reason': 'Run install_openmm.py once'}
    directory = Path(output) / ('openmm_' + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True)
    request = {'system': 'aqueous_LiCl_benchmark', 'production_ps': production_ps, 'seed': seed}
    (directory/'input.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='spe_openmm_') as mirror_root, (directory/'stdout.log').open('w') as out, (directory/'stderr.log').open('w') as err:
        try:
            env = dict(os.environ, SPE_OPENMM_MIRROR=mirror_root)
            proc = subprocess.run([str(MD_PYTHON), str(ROOT/'openmm_worker.py'), str(directory)],
                                  stdout=out, stderr=err, timeout=1800, env=env,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except subprocess.TimeoutExpired:
            return {'status': 'failed', 'error_category': 'timeout', 'artifact_dir': str(directory)}
    if proc.returncode or not (directory/'result.json').is_file():
        return {'status': 'failed', 'error_category': 'engine_error',
                'exit_code': proc.returncode, 'artifact_dir': str(directory),
                'error_log': str(directory/'stderr.log')}
    return json.loads((directory/'result.json').read_text(encoding='utf-8'))
