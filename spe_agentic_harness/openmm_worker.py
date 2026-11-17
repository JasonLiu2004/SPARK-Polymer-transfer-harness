"""Subprocess isolation keeps OpenMM DLL/runtime settings out of the planner."""
import csv
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import sys
import tempfile
import time

# Native faults must become a recorded subprocess failure, never desktop dialogs.
if os.name == 'nt':
    import ctypes
    ctypes.windll.kernel32.SetErrorMode(0x0001 | 0x0002 | 0x8000)
import faulthandler
faulthandler.enable()

sys.path.insert(0, str(Path(__file__).resolve().parent))
from diffusion import RUNTIME, analyze
RUNTIME = Path(__file__).resolve().parent/'.runtime'/'md_env'/'Lib'/'site-packages'
# OpenMM's Windows C++ plugin loader cannot handle this project's Chinese path.
# A per-process temporary DLL mirror avoids modifying PATH/global installations.
_dll_cache = None if os.environ.get('SPE_OPENMM_MIRROR') else tempfile.TemporaryDirectory(prefix='spe_openmm_', ignore_cleanup_errors=True)
mirror = Path(os.environ.get('SPE_OPENMM_MIRROR') or _dll_cache.name)/'runtime'
mirror.mkdir()
for package in ('openmm', 'OpenMM.libs'):
    shutil.copytree(RUNTIME/package, mirror/package)
sys.path.insert(0, str(mirror))
lib = mirror/'OpenMM.libs'/'lib'
os.environ['OPENMM_PLUGIN_DIR'] = str(lib/'plugins')
if '--no-plugins' in sys.argv:
    (mirror/'empty').mkdir()
    os.environ['OPENMM_PLUGIN_DIR'] = str(mirror/'empty')
_dll_handles = [os.add_dll_directory(str(lib)),
                os.add_dll_directory(str(lib/'plugins'))] if os.name == 'nt' else []
import numpy as np
import openmm as mm
from openmm import app, unit
print('OpenMM imported', mm.__version__, flush=True)
print('Plugins', mm.Platform.getPluginLoadFailures(), flush=True)
print('Platforms', [mm.Platform.getPlatform(i).getName() for i in range(mm.Platform.getNumPlatforms())], flush=True)


def main(directory):
    start = time.monotonic()
    request = json.loads((directory/'input.json').read_text())
    seed = request['seed']
    random.seed(seed)
    ff = app.ForceField('amber14/tip3p.xml')
    model = app.Modeller(app.Topology(), [] * unit.nanometer)
    model.addSolvent(ff, boxSize=mm.Vec3(2.4, 2.4, 2.4)*unit.nanometer,
                     positiveIon='Li+', negativeIon='Cl-', ionicStrength=1*unit.molar)
    print('Solvent built', flush=True)
    system = ff.createSystem(model.topology, nonbondedMethod=app.PME,
                             nonbondedCutoff=1*unit.nanometer, constraints=app.HBonds,
                             rigidWater=True, removeCMMotion=True)
    integrator = mm.LangevinMiddleIntegrator(300*unit.kelvin, 1/unit.picosecond, .002*unit.picoseconds)
    integrator.setRandomNumberSeed(seed)
    sim = app.Simulation(model.topology, system, integrator,
                         mm.Platform.getPlatformByName('CPU'), {'Threads': '2'})
    print('Context created', flush=True)
    sim.context.setPositions(model.positions)
    sim.minimizeEnergy(maxIterations=1000)
    sim.context.setVelocitiesToTemperature(300*unit.kelvin, seed)
    sim.reporters.append(app.StateDataReporter(str(directory/'thermodynamics.csv'), 500,
                         step=True, time=True, potentialEnergy=True, temperature=True))
    # Fixed-volume NVT smoke benchmark; density/equilibration not validated.
    sim.step(10000)  # 20 ps equilibration, excluded from diffusion analysis.
    atoms = list(model.topology.atoms())
    indices = {symbol: [a.index for a in atoms if a.element.symbol == symbol] for symbol in ('Li', 'Cl')}
    if not all(indices.values()):
        raise ValueError('No ions were inserted')
    with (directory/'initial.pdb').open('w') as f:
        app.PDBFile.writeFile(model.topology, sim.context.getState(getPositions=True).getPositions(), f)
    (directory/'system.xml').write_text(mm.XmlSerializer.serialize(system), encoding='utf-8')
    (directory/'integrator.xml').write_text(mm.XmlSerializer.serialize(integrator), encoding='utf-8')
    # OpenMM context coordinates with enforcePeriodicBox=False are continuous.
    # Save every atom so trajectory can be reanalysed independently.
    frames = []
    for i in range(request['production_ps']*10 + 1):
        if i:
            sim.step(50)  # 0.1 ps between snapshots
        state = sim.context.getState(getPositions=True, enforcePeriodicBox=False)
        frames.append(state.getPositions(asNumpy=True).value_in_unit(unit.nanometer))
        if i % 200 == 0:
            print(f'Production {i/10:.1f} ps', flush=True)
    trajectory = np.asarray(frames)
    if not np.isfinite(trajectory).all():
        raise ValueError('Non-finite MD coordinates')
    np.savez_compressed(directory/'trajectory.npz', positions_nm=trajectory,
                        time_ps=np.arange(len(frames))*.1, box_nm=np.eye(3)*2.4,
                        symbols=np.array([a.element.symbol for a in atoms]))
    metrics = {}
    for symbol, selection in indices.items():
        values = analyze(trajectory[:, selection, :], .1)
        with (directory/f'msd_{symbol}.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['lag_ps', 'msd_nm2'])
            writer.writerows(zip(values.pop('lag_ps'), values.pop('msd_nm2')))
        metrics[symbol] = {**values, 'ion_count': len(selection)}
    sim.saveState(str(directory/'final_state.xml'))
    result = {'status': 'completed', 'origin': 'md_simulation', 'engine': 'OpenMM',
              'engine_version': mm.__version__, 'system': request['system'],
              'python_executable': sys.executable, 'python_version': sys.version,
              'numpy_version': np.__version__,
              'forcefield': 'amber14/tip3p.xml', 'temperature_K': 300,
              'ensemble': 'NVT', 'box_nm': [2.4]*3, 'atom_count': len(atoms),
              'actual_salt_concentration_mol_L': len(indices['Li'])/(6.02214076e23*2.4**3*1e-24),
              'equilibration_ps': 20, 'production_ps': request['production_ps'],
              'timestep_ps': .002, 'sampling_interval_ps': .1, 'seed': seed,
              'analysis': 'Multi-time-origin self MSD, continuous coordinates, slope/6',
              'metrics': metrics, 'converged': False, 'eligible_for_ranking': False,
              'limitations': ['Aqueous LiCl, not a solid polymer electrolyte',
                             'Single short replica; equilibration and diffusion convergence unverified',
                             'No finite-size correction or independent-replica uncertainty',
                             'Langevin thermostat and force field affect transport; no experimental validation'],
              'artifact_dir': str(directory), 'elapsed_seconds': time.monotonic()-start,
              'trajectory_sha256': hashlib.sha256((directory/'trajectory.npz').read_bytes()).hexdigest()}
    (directory/'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    if sys.argv[1] == '--probe':
        system = mm.System()
        system.addParticle(1)
        integrator = mm.VerletIntegrator(.001)
        platform_name = sys.argv[2] if len(sys.argv) > 2 else 'CPU'
        context = mm.Context(system, integrator, mm.Platform.getPlatformByName(platform_name), {'Threads': '2'} if platform_name == 'CPU' else {})
        context.setPositions([[0, 0, 0]])
        integrator.step(10)
        print('PROBE_OK', flush=True)
    else:
        main(Path(sys.argv[1]).resolve())
