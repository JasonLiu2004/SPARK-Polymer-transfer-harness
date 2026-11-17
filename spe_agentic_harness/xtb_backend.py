"""Real, project-managed GFN2-xTB fragment/Li+ calculations.

No mock values or local shell evaluation. The bundled official portable engine
is discovered automatically, without touching the user's global environment.
"""
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import uuid


SYMBOLS = {'H': 1, 'Li': 3, 'C': 6, 'N': 7, 'O': 8, 'F': 9, 'P': 15, 'S': 16, 'Cl': 17}
HARTREE_TO_KJMOL = 2625.4996394799


def discover_xtb_backend(output_dir):
    executable = Path(__file__).resolve().parent / '.runtime' / 'xtb' / 'xtb-6.7.1' / 'bin' / 'xtb.exe'
    return XTBBackend(executable, output_dir) if executable.is_file() else None


def write_xyz(path, geometry):
    lines = [str(len(geometry['symbols'])), 'Harness-generated starting geometry; Angstrom']
    for symbol, xyz in zip(geometry['symbols'], geometry['positions_angstrom']):
        lines.append(f'{symbol} {xyz[0]:.12f} {xyz[1]:.12f} {xyz[2]:.12f}')
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')


def read_xyz(path, expected_symbols):
    lines = path.read_text(encoding='utf-8').splitlines()
    if int(lines[0]) != len(expected_symbols):
        raise ValueError('Optimized structure atom count mismatch')
    rows = [line.split() for line in lines[2:2 + len(expected_symbols)]]
    if [r[0] for r in rows] != expected_symbols:
        raise ValueError('Optimized structure atom ordering mismatch')
    positions = [[float(v) for v in r[1:4]] for r in rows]
    if any(len(p) != 3 or any(not math.isfinite(x) for x in p) for p in positions):
        raise ValueError('Invalid optimized coordinates')
    return {'symbols': expected_symbols, 'positions_angstrom': positions}


class XTBBackend:
    is_test_backend = False
    supported_pairs = frozenset({('calculate_coordination', 'xtb')})

    def __init__(self, executable, output_dir, timeout_seconds=120):
        self.executable = Path(executable).resolve()
        self.output = Path(output_dir).resolve()
        self.timeout = timeout_seconds

    def run(self, request):
        if (request.get('task'), request.get('engine')) not in self.supported_pairs:
            raise ValueError('This backend only supports calculate_coordination/xtb')
        system = request['payload']['system']
        fragment, ion = system['fragment'], system['ion']
        if fragment['charge'] != 0 or ion['symbols'] != ['Li'] or ion['charge'] != 1:
            raise ValueError('v1 supports a neutral molecular fragment and one Li+ ion')
        if fragment['multiplicity'] != 1 or ion['multiplicity'] != 1:
            raise ValueError('v1 supports closed-shell singlet fragments and Li+')
        if not 2 <= len(fragment['symbols']) <= 64:
            raise ValueError('Fragment size must be 2..64 atoms')
        if any(s not in SYMBOLS for s in fragment['symbols']):
            raise ValueError('Unsupported element in fragment')
        if sum(SYMBOLS[s] for s in fragment['symbols']) % 2:
            raise ValueError('Neutral singlet fragment must have an even number of electrons')
        complex_geometry = {'symbols': fragment['symbols'] + ion['symbols'],
                            'positions_angstrom': fragment['positions_angstrom'] + ion['positions_angstrom'],
                            'charge': 1, 'multiplicity': 1}
        positions = complex_geometry['positions_angstrom']
        if any(math.dist(a, b) < .4 for i, a in enumerate(positions) for b in positions[:i]):
            raise ValueError('Overlapping starting atoms (<0.4 Angstrom)')
        output = self.output / (request['request_id'][:16] + '_' + uuid.uuid4().hex[:8])
        output.mkdir(parents=True)
        (output / 'request.json').write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding='utf-8')
        base = {'request_id': request['request_id'], 'task': request['task'], 'engine': 'xtb',
                'data_origin': 'quantum_calculation', 'artifact_dir': str(output),
                'method': 'GFN2-xTB gas-phase optimized electronic binding energy',
                'engine_version': '6.7.1pre', 'converged': False,
                'executable_sha256': hashlib.sha256(self.executable.read_bytes()).hexdigest()}
        try:
            version = subprocess.run([str(self.executable), '--version'], capture_output=True,
                                     timeout=15, creationflags=self._flags(), env=self._env())
            version_text = (version.stdout + version.stderr).decode('utf-8', errors='replace')
            (output / 'engine_version.txt').write_text(version_text, encoding='utf-8')
            if version.returncode or '6.7.1pre' not in version_text:
                raise RuntimeError('Unexpected executable version')
            parts = {}
            for name, geometry in [('fragment', fragment), ('ion', ion), ('complex', complex_geometry)]:
                parts[name] = self._calculate(output / name, geometry, optimize=name != 'ion')
            delta = parts['complex']['energy_hartree'] - parts['fragment']['energy_hartree'] - parts['ion']['energy_hartree']
            optimized = parts['complex']['geometry']
            li_position = optimized['positions_angstrom'][-1]
            distances = [{'atom_index': i, 'element': s, 'distance_angstrom': math.dist(li_position, optimized['positions_angstrom'][i])}
                         for i, s in enumerate(fragment['symbols']) if s in ('O', 'N', 'S', 'F', 'Cl')]
            result = {**base, 'status': 'completed', 'converged': True,
                      'metrics': {'binding_energy': {'value': delta * HARTREE_TO_KJMOL, 'unit': 'kJ/mol'}},
                      'energy_definition': 'E(optimized fragment+Li+) - E(optimized neutral fragment) - E(isolated Li+)',
                      'energies_hartree': {name: p['energy_hartree'] for name, p in parts.items()},
                      'optimized_complex': optimized, 'li_donor_distances': distances,
                      'conditions': {'phase': 'gas', 'implicit_solvent': None, 'temperature_K': None,
                                     'optimization': 'tight', 'gfn': 2, 'uhf': 0},
                      'limitations': ['Local minimum from one starting geometry; no conformer search',
                                      'Electronic energy only; no ZPE, thermal or entropic correction',
                                      'Small fragment model, not a polymer electrolyte conductivity calculation',
                                      'No frequency check of the stationary structures'],
                      'parts': parts}
        except Exception as exc:
            result = {**base, 'status': 'failed', 'error': {'type': type(exc).__name__, 'message': str(exc)}}
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        return result

    @staticmethod
    def _flags():
        return subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

    def _env(self):
        env = os.environ.copy()
        env.update(OMP_NUM_THREADS='2', MKL_NUM_THREADS='2', OMP_STACKSIZE='256M',
                   XTBPATH=str(self.executable.parent.parent / 'share' / 'xtb'))
        return env

    def _calculate(self, folder, geometry, optimize):
        folder.mkdir()
        write_xyz(folder / 'input.xyz', geometry)
        command = [str(self.executable), 'input.xyz', '--gfn', '2', '--chrg', str(geometry['charge']),
                   '--uhf', '0', '--acc', '0.2', '--iterations', '250', '--json']
        if optimize:
            command += ['--opt', 'tight', '--cycles', '200']
        (folder / 'command.json').write_text(json.dumps(command, indent=2), encoding='utf-8')
        # Relative ASCII filenames avoid encoding problems in native Fortran I/O.
        with (folder / 'stdout.log').open('wb') as stdout, (folder / 'stderr.log').open('wb') as stderr:
            done = subprocess.run(command, cwd=folder, env=self._env(), stdout=stdout, stderr=stderr,
                                  timeout=self.timeout, creationflags=self._flags())
        text = (folder / 'stdout.log').read_text(encoding='utf-8', errors='replace')
        err = (folder / 'stderr.log').read_text(encoding='utf-8', errors='replace')
        if done.returncode or 'normal termination of xtb' not in (text + err).lower():
            raise RuntimeError(f'xTB {folder.name} failed; inspect stdout.log/stderr.log')
        if 'convergence criteria satisfied' not in text.lower():
            raise RuntimeError(f'xTB {folder.name} electronic convergence not confirmed')
        if optimize and ('GEOMETRY OPTIMIZATION CONVERGED' not in text.upper() or not (folder / 'xtbopt.xyz').exists()):
            raise RuntimeError(f'xTB {folder.name} geometry did not converge')
        energies = re.findall(r'TOTAL ENERGY\s+([-+\d.Ee]+)\s+Eh', text)
        if not energies or not math.isfinite(float(energies[-1])):
            raise RuntimeError(f'xTB {folder.name} has no finite final energy')
        optimized = read_xyz(folder / ('xtbopt.xyz' if optimize else 'input.xyz'), geometry['symbols'])
        return {'energy_hartree': float(energies[-1]), 'geometry': optimized,
                'artifact_dir': str(folder), 'exit_code': done.returncode, 'optimized': optimize}
