#!/usr/bin/env python3
"""Validate CENTURY scenarios and prepare deterministic Slurm array assignments.

Dry-run only. Reads the production TOML and basin manifest.
Does not modify model inputs, create outputs, or submit jobs.
"""

import argparse
import tomllib
from pathlib import Path


def load(path):
    with path.open("rb") as f:
        return tomllib.load(f)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--preview-all", action="store_true",
                        help="Preview all available algorithms without enabling them")
    parser.add_argument("--task-index", type=int,
                        help="Inspect one zero-based Slurm array task")
    args = parser.parse_args()

    scenario = args.scenario.resolve()
    exp = scenario.parent.parent
    cfg = load(scenario)

    manifest = load(exp / cfg["dataset"]["manifest"])
    basins = manifest["multi_case"]["case_names"]
    opt = cfg["optimization"]

    available = opt["available_algorithms"]
    selected = available if args.preview_all else opt["selected_algorithms"]
    runs = opt["independent_runs"]
    budget = opt["evaluations"]
    seed_base = opt["seed_base"]

    assert len(basins) == cfg["dataset"]["expected_basins"]
    assert len(basins) == len(set(basins))
    assert len(available) == len(set(available))
    assert len(selected) == len(set(selected))
    assert set(selected).issubset(available)
    assert runs > 0 and budget > 0
    assert cfg["execution"]["mpi_processes"] == 1

    data = Path(cfg["dataset"]["root"]) / "domain"
    missing = [b for b in basins if not (data / b).is_dir()]
    if missing:
        raise SystemExit(f"Missing basin directories: {missing}")

    tasks = [
        (alg, basin, run, seed_base + run - 1)
        for alg in selected
        for basin in basins
        for run in range(1, runs + 1)
    ]

    if args.task_index is not None:
        if not 0 <= args.task_index < len(tasks):
            parser.error("Task index outside the configured task range")
        alg, basin, run, seed = tasks[args.task_index]
        print(f"TASK_INDEX={args.task_index}")
        print(f"ALGORITHM={alg}")
        print(f"BASIN={basin}")
        print(f"RUN_INDEX={run}")
        print(f"SEED={seed}")
        return

    print("CONFIGURATION: PASS")
    print("Basins:", len(basins))
    print("Algorithms:", ", ".join(selected) or "Not selected")
    print("Independent runs:", runs)
    print("Evaluations per task:", budget)
    print("Total array tasks:", len(tasks))
    print("Concurrent task limit:", cfg["execution"]["max_concurrent_jobs"])
    print("Production enabled:", cfg["experiment"]["production_enabled"])
    print("Mode: DRY RUN ONLY")

    print("\nFIRST FIVE TASK ASSIGNMENTS")
    for index, task in enumerate(tasks[:5]):
        alg, basin, run, seed = task
        print(f"{index:4d}: {alg:12s} {basin:14s} run={run} seed={seed}")

    if not selected:
        print("\nNo algorithms selected. Scenario design is still pending.")


if __name__ == "__main__":
    main()
