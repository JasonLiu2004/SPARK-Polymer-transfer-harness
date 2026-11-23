"""Run a five-window forecast, inspect a sealed run, or use the earlier harnesses."""
import argparse
from pathlib import Path
import subprocess
import sys

from spe_agentic_harness.config import load_env


ROOT = Path(__file__).resolve().parent
RANKING = Path("Polymer_Agentic_Ranking_Harness")
INPUTS = Path("Polymer_Adoption_Harness")
SCRIPTS = {
    "sources": INPUTS / "prepare_sources.py",
    "hpg-grid": INPUTS / "physics.py",
    "rank": RANKING / "run.py",
    "rank-paratera": RANKING / "run_paratera.py",
    "rank-resume-paratera": RANKING / "resume_paratera.py",
    "rank-audit": RANKING / "audit.py",
    "rank-explain": RANKING / "explain.py",
    "rank-report": RANKING / "report.py",
    "temporal": "temporal_harness/run.py",
    "smoke": "spark_agentic_harness/run.py",
    "completion": "spark_agentic_harness/run_completion_demo.py",
    "plan": "spark_agentic_harness/run.py",
    "batch10": "spark_agentic_harness/run_batch10.py",
    "case": "spark_agentic_harness/run_case_study.py",
    "hpg": "spark_agentic_harness/external_conductivity/test_public_hpg.py",
    "scan": "spark_agentic_harness/external_conductivity/test_public_scan.py",
    "baseline": "spark_agentic_harness/external_conductivity/test_structure_baseline.py",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=[*SCRIPTS, "test-ranking", "test"])
    command = parser.parse_args(sys.argv[1:2]).command
    extra = sys.argv[2:]
    python = [sys.executable, "-X", "utf8", "-B"]
    if command in ("test", "test-ranking"):
        folders = [INPUTS, RANKING] if command == "test-ranking" else ["spe_agentic_harness", "spark_agentic_harness"]
        for folder in folders:
            args = ["-m", "unittest", "discover", "-s", str(ROOT / folder), "-p", "test_*.py", *extra]
            status = subprocess.run(python + args, cwd=ROOT).returncode
            if status:
                return status
        return 0
    if command == "plan" and "--task" not in extra:
        parser.error('plan requires --task "研究问题"')
    if command in ("rank", "rank-paratera", "rank-resume-paratera"):
        load_env(ROOT / ".env")
    return subprocess.run([*python, str(ROOT / SCRIPTS[command]), *extra], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
