#!/bin/bash
#SBATCH --job-name=century_python
#SBATCH --account=rrg-mclark
#SBATCH --partition=cpubase_bycore_b4
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=36:00:00
#SBATCH --output=/home/armanhad/projects/rrg-mclark/armanhad/hydro_models/experiments/century/MM/exp57/logs/production_%A_%a.out
#SBATCH --error=/home/armanhad/projects/rrg-mclark/armanhad/hydro_models/experiments/century/MM/exp57/logs/production_%A_%a.err

set -euo pipefail

# One Slurm array per scenario and algorithm.
# Preview: ALGORITHM=ga bash run_production_array.sh --preview 0
# Run:     submit with sbatch --array after approving the scenario.
# Never automatically submit jobs.

ROOT="/home/armanhad/projects/rrg-mclark/armanhad/hydro_models"
EXP="$ROOT/experiments/century/MM/exp57"
MODE="${1:---preview}"
INDEX="${2:-${SLURM_ARRAY_TASK_ID:-0}}"
SCENARIO_CONFIG="${SCENARIO_CONFIG:-$EXP/settings/production_scenarios.toml}"
ALGORITHM="${ALGORITHM:-}"

if [[ "$MODE" != "--preview" && "$MODE" != "--run" ]]; then
    echo "Usage: ALGORITHM=ga bash $0 --preview [task_index]"
    exit 2
fi

if [[ "$MODE" == "--run" ]]; then
    : "${SLURM_ARRAY_JOB_ID:?Slurm array required}"
    : "${SLURM_ARRAY_TASK_ID:?Slurm task ID required}"
    : "${SLURM_TMPDIR:?Node-local scratch required}"

    # Do not allow a submitted task to override its Slurm index.
    INDEX="$SLURM_ARRAY_TASK_ID"

    source "$ROOT/summa_vpr675_python/load_model_env_fir.sh"
    module load scipy-stack/2024b
    if [[ "$ALGORITHM" == "cmaes" || "$ALGORITHM" == "sceua" ]]; then
        module load mpi4py/4.0.0
    fi

    SCIPY_STACK=$(python3 -c \
      'import numpy,pathlib; print(pathlib.Path(numpy.__file__).parent.parent)')
    export PYTHONPATH="$SCIPY_STACK${PYTHONPATH:+:$PYTHONPATH}"
    export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
fi

"$ROOT/venvs/summa_ray/bin/python" - \
    "$ROOT" "$EXP" "$MODE" "$INDEX" "$SCENARIO_CONFIG" "$ALGORITHM" <<'PY'
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path

root, exp = map(Path, sys.argv[1:3])
mode, index = sys.argv[3], int(sys.argv[4])
scenario_path = Path(sys.argv[5]).resolve()
algorithm = sys.argv[6]


def load(path):
    with path.open("rb") as f:
        return tomllib.load(f)


def stamp():
    return datetime.now(timezone.utc).isoformat()


cfg = load(scenario_path)
opt = cfg["optimization"]
manifest = load(exp / cfg["dataset"]["manifest"])
basins = manifest["multi_case"]["case_names"]

runners = {
    "ga": "pymoo_calibration/run_calibration.py",
    "de": "run_de_calibration.py",
    "cmaes": "run_cmaes_calibration.py",
    "custom_dds": "algorithms/custom_dds.py",
    "spotpy_dds": "algorithms/spotpy_dds.py",
    "sceua": "algorithms/sceua.py",
}

options = {
    "ga": ["--algorithm", "ga", "--population-size", "10"],
    "de": ["--population-size", "10", "--mutation", "0.8",
           "--crossover", "0.7"],
    "cmaes": ["--population-size", "10", "--sigma", "0.2"],
    "custom_dds": ["--boundary-method", "reflect",
                   "--perturbation-scale", "0.2"],
    "spotpy_dds": ["--perturbation-scale", "0.2"],
    "sceua": ["--ngs", "1", "--kstop", "100"],
}

if algorithm == "ga":
    g = cfg["ga"]
    options["ga"] = [
        "--algorithm", "ga",
        "--population-size", str(g["population_size"]),
        "--crossover-prob", str(g["crossover_probability"]),
        "--crossover-eta", str(g["crossover_eta"]),
        "--mutation-prob", str(g["mutation_probability_per_variable"]),
        "--mutation-eta", str(g["mutation_eta"]),
    ]

if algorithm == "de":
    d = cfg["de"]
    options["de"] = [
        "--population-size", str(d["population_size"]),
        "--strategy", str(d["strategy"]),
        "--mutation", str(d["mutation_factor"]),
        "--crossover", str(d["crossover_probability"]),
    ]

elif algorithm == "cmaes":
    c = cfg["cmaes"]
    options["cmaes"] = [
        "--population-size", str(c["population_size"]),
        "--sigma", str(c["initial_sigma"]),
    ]

elif algorithm == "sceua":
    s = cfg["sceua"]
    options["sceua"] = [
        "--ngs", str(s["ngs"]),
        "--kstop", str(s["kstop"]),
        "--peps", str(s["peps"]),
        "--pcento", str(s["pcento"]),
    ]

if algorithm not in runners or algorithm not in opt["available_algorithms"]:
    raise SystemExit(f"Invalid or missing ALGORITHM: {algorithm}")

if len(basins) != cfg["dataset"]["expected_basins"] or len(basins) != len(set(basins)):
    raise SystemExit("Basin manifest verification failed")

runs = opt["independent_runs"]
budget = opt["evaluations"]
if runs < 1 or budget < 1:
    raise SystemExit("Invalid run count or evaluation budget")

tasks = [(basin, run) for basin in basins for run in range(1, runs + 1)]
if not 0 <= index < len(tasks):
    raise SystemExit(f"Task index out of range: 0-{len(tasks)-1}")

basin, run = tasks[index]
seed = opt["seed_base"] + run - 1

# Scenario ID isolates results for different scientific experiments.
scenario_id = cfg["experiment"].get("scenario_id", scenario_path.stem)
if not re.fullmatch(r"[A-Za-z0-9_-]+", scenario_id):
    raise SystemExit("Invalid scenario ID")

template = exp / cfg["model"]["template"]
runner = root / "summa_python_wrapper/python_wrapper" / runners[algorithm]
library = root / "builds/summa_vpr675_python/libsumma.so"
python = root / "venvs/summa_ray/bin/python"
launcher = exp / "settings/run_production_array.sh"
verifier = exp / "settings/verify_calibration.py"

results = (
    exp / cfg["output"]["directory"] / scenario_id /
    algorithm / basin / f"run{run:04d}"
)
prefix = results / f"{basin}_run{run:04d}"

print(f"Scenario: {scenario_id}")
print(f"Algorithm: {algorithm}")
print(f"Basin: {basin}")
print(f"Run: {run}, seed: {seed}")
print(f"Task: {index}/{len(tasks)-1}")
print(f"Evaluations: {budget}")
print(f"Results: {results}")
print(f"Production enabled: {cfg['experiment']['production_enabled']}")

if mode == "--preview":
    print("PREVIEW PASS: no files written and no jobs submitted")
    raise SystemExit(0)

# Execution is deliberately blocked until scenario design is approved.
if not cfg["experiment"]["production_enabled"]:
    raise SystemExit("BLOCKED: production is disabled")
if algorithm not in opt["selected_algorithms"]:
    raise SystemExit("BLOCKED: algorithm is not selected")
if cfg["execution"]["mpi_processes"] != 1:
    raise SystemExit("Only the validated single-worker MPI launch is supported")

for path in (template, runner, library, python, launcher, verifier):
    if not path.is_file():
        raise SystemExit(f"Missing dependency: {path}")

if not (Path(cfg["dataset"]["root"]) / "domain" / basin).is_dir():
    raise SystemExit(f"Missing basin: {basin}")

# Fingerprint input configuration and executable components.
digest = hashlib.sha256()
for path in (scenario_path, template, runner, launcher, verifier):
    digest.update(path.read_bytes())
stat = library.stat()
digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
fingerprint = digest.hexdigest()

# Import the six-algorithm NetCDF verifier already tested.
spec = importlib.util.spec_from_file_location("calibration_verify", verifier)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

marker = results / "completion.json"

if marker.exists():
    previous = json.loads(marker.read_text())
    if previous.get("fingerprint") != fingerprint:
        raise SystemExit("Existing completed run uses different code/configuration")
    module.verify(results, algorithm, budget)
    print("SKIPPED: previously completed and verified")
    raise SystemExit(0)

# Never overwrite incomplete or potentially valuable NetCDF results.
if results.exists() and any(results.iterdir()):
    raise SystemExit(f"Existing incomplete results; inspect before retry: {results}")

# Create an exclusive lock to prevent concurrent duplicate execution.
results.parent.mkdir(parents=True, exist_ok=True)
lock = results.with_name(results.name + ".lock")
try:
    lock.mkdir()
except FileExistsError:
    raise SystemExit(f"Task already running or stale lock: {lock}")

try:
    work = Path(os.environ["SLURM_TMPDIR"]) / f"century_{index}"
    (work / "summa_work").mkdir(parents=True, exist_ok=True)
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)

    # Keep cold-state input accessible, but write restarts
    # only to this task's private node-local directory.
    state_dir = work / "summa_state"
    state_dir.mkdir(parents=True, exist_ok=True)

    source_state = (
        Path(cfg["dataset"]["root"]) /
        "domain" / basin / "summa_state" / "coldState.nc"
    )
    if not source_state.is_file():
        raise RuntimeError(f"Missing cold state: {source_state}")

    (state_dir / "coldState.nc").symlink_to(source_state)

    config = work / "summa_config.toml"
    text = template.read_text()

    for old, new in {
        "{home}": "/home/armanhad/projects/rrg-mclark",
        "{case_name}": basin,
        "{basin_dir}": f"datasets/nawm/century/domain/{basin}",
        "{experiment}": cfg["experiment"]["name"],
    }.items():
        text = text.replace(old, new)

    text, state_count = re.subn(
        r'(?m)^state_path\s*=\s*"[^"]*"',
        f'state_path = "{state_dir}/"',
        text,
    )
    if state_count != 1:
        raise RuntimeError("Could not redirect state_path")

    text, count = re.subn(
        r'(?m)^output_path\s*=\s*"[^"]*"',
        f'output_path = "{work / "summa_work"}/"', text,
    )
    if count != 1 or re.search(r"\{[A-Za-z_]\w*\}", text):
        raise RuntimeError("Configuration rendering failed")

    # Match the scientific template's trial budget to the scenario.
    text, count = re.subn(
        r'(?m)^(\s*n_samples\s*=\s*)\d+',
        lambda m: m.group(1) + str(budget), text,
    )
    if count != 1:
        raise RuntimeError("Expected exactly one n_samples entry")

    parsed = tomllib.loads(text)
    if parsed["simulation"]["case_name"] != basin:
        raise RuntimeError("Incorrect basin configuration")

    config.write_text(text)
    env = os.environ.copy()
    env["TMPDIR"] = str(work / "tmp")

    command = [
        str(python), str(runner),
        "--config", str(config),
        "--library", str(library),
        "--output-prefix", str(prefix),
        "--run-index", str(run),
        "--n-evaluations", str(budget),
        "--seed", str(seed),
    ] + options[algorithm]

    # Save resolved scientific configuration for reproducibility.
    (results / "resolved_config.toml").write_text(text)

    metadata = {
        "scenario": scenario_id,
        "algorithm": algorithm,
        "basin": basin,
        "run_index": run,
        "seed": seed,
        "budget": budget,
        "fingerprint": fingerprint,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_array_task_id": index,
        "started_utc": stamp(),
    }

    (results / "run_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n"
    )

    subprocess.run(command + ["--dry-run"], check=True, cwd=work, env=env)
    subprocess.run(["mpirun", "-np", "1"] + command,
                   check=True, cwd=work, env=env)

    # Mark complete only after both native NetCDF files pass verification.
    module.verify(results, algorithm, budget)
    metadata["completed_utc"] = stamp()

    temporary = results / f"completion.json.tmp.{os.getpid()}"
    temporary.write_text(json.dumps(metadata, indent=2) + "\n")
    os.replace(temporary, marker)

    print("PRODUCTION TASK: VERIFIED COMPLETE", flush=True)

finally:
    lock.rmdir()
PY
