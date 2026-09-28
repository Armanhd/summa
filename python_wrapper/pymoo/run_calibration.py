#!/usr/bin/env python3

import argparse
import csv
import json
import multiprocessing as mp
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.core.problem import ElementwiseProblem
from pymoo.optimize import minimize
from pymoo.parallelization.starmap import StarmapParallelization


HERE = Path(__file__).resolve().parent
WRAPPER_DIR = HERE.parent

sys.path.insert(0, str(WRAPPER_DIR))
sys.path.insert(0, str(HERE))

from summa_ctypes import SummaModel
from calibration_config import (
    EXP5,
    LIBSUMMA,
    PARAMETERS,
    DEFAULT_POPULATION,
    DEFAULT_GENERATIONS,
    DEFAULT_SEED,
)


# ============================================================
# Persistent process-local SUMMA model
# ============================================================

_worker_model = None


# ============================================================
# Parameter transformations
# ============================================================

def optimizer_bounds():

    lower = []
    upper = []

    for p in PARAMETERS:

        if p["transform"] == "log10":
            lower.append(np.log10(p["lower"]))
            upper.append(np.log10(p["upper"]))

        else:
            lower.append(p["lower"])
            upper.append(p["upper"])

    return np.asarray(lower), np.asarray(upper)


def decode_parameters(x):

    params = {}

    for definition, value in zip(PARAMETERS, x):

        if definition["transform"] == "log10":
            physical_value = 10.0 ** float(value)

        else:
            physical_value = float(value)

        params[definition["name"]] = physical_value

    return params


# ============================================================
# Worker initialization
# ============================================================

def initialize_worker(config_queue):

    global _worker_model

    config_path = config_queue.get()

    # Suppress SUMMA/Fortran timestep output inside production
    # optimizer workers. This avoids huge Slurm log files.
    devnull = os.open(os.devnull, os.O_WRONLY)

    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

    os.close(devnull)

    _worker_model = SummaModel(
        library_path=str(LIBSUMMA),
        config_path=str(config_path),
    )


# ============================================================
# Pymoo model problem
# ============================================================

class SummaCalibrationProblem(ElementwiseProblem):

    def __init__(self, runner):

        lower, upper = optimizer_bounds()

        super().__init__(
            n_var=len(PARAMETERS),
            n_obj=1,
            xl=lower,
            xu=upper,
            elementwise_runner=runner,
        )

    def _evaluate(self, x, out, *args, **kwargs):

        parameters = decode_parameters(x)

        kge = _worker_model.evaluate(parameters)

        # Pymoo minimizes. Therefore:
        #
        # maximize KGE == minimize -KGE
        out["F"] = -float(kge)


# ============================================================
# Runtime preparation
# ============================================================

def prepare_runtime(basin, nworkers):

    base_config = (
        EXP5
        / "python_wrapper"
        / "configs"
        / f"{basin}.toml"
    )

    if not base_config.is_file():
        raise FileNotFoundError(
            f"Missing basin configuration: {base_config}"
        )

    domain = EXP5 / "domain" / basin

    cold_state = (
        domain
        / "summa_state"
        / "coldState.nc"
    )

    if not cold_state.is_file():
        raise FileNotFoundError(
            f"Missing coldState: {cold_state}"
        )

    # Prefer node-local temporary storage.
    #
    # On Slurm this normally avoids repeated writes to the shared
    # /work filesystem during the calibration.
    tmp_root = os.environ.get("SLURM_TMPDIR")

    if tmp_root:

        runtime_root = (
            Path(tmp_root)
            / "summa_pymoo"
            / basin
        )

    else:

        runtime_root = (
            EXP5
            / "python_wrapper"
            / "runtime"
            / basin
        )

    if runtime_root.exists():
        shutil.rmtree(runtime_root)

    runtime_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    base_text = base_config.read_text()

    configs = []

    for i in range(nworkers):

        worker_dir = (
            runtime_root
            / f"worker_{i:03d}"
        )

        state_dir = worker_dir / "state"
        work_dir = worker_dir / "work"

        state_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        work_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        worker_cold = (
            state_dir
            / "coldState.nc"
        )

        worker_cold.symlink_to(
            cold_state
        )

        text = base_text

        text = text.replace(
            'state_path   = "{home}/{basin_dir}/summa_state/"',
            f'state_path   = "{state_dir}/"',
        )

        text = text.replace(
            'work_path = "{home}/{basin_dir}/work/"',
            f'work_path = "{work_dir}/"',
        )

        config_path = (
            worker_dir
            / "config.toml"
        )

        config_path.write_text(text)

        configs.append(config_path)

    return runtime_root, configs


# ============================================================
# Write calibration history
# ============================================================

def write_history(
    result,
    basin,
    results_dir,
):

    results_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    csv_file = (
        results_dir
        / f"{basin}_pymoo_history.csv"
    )

    parameter_names = [
        p["name"]
        for p in PARAMETERS
    ]

    with csv_file.open(
        "w",
        newline="",
    ) as f:

        writer = csv.writer(f)

        writer.writerow(
            [
                "generation",
                "individual",
                "kge",
                *parameter_names,
            ]
        )

        for generation_index, algorithm in enumerate(
            result.history,
            start=1,
        ):

            population = algorithm.pop

            X = population.get("X")
            F = population.get("F")

            for individual, (x, fval) in enumerate(
                zip(X, F),
                start=1,
            ):

                params = decode_parameters(x)

                kge = -float(
                    np.asarray(fval).reshape(-1)[0]
                )

                writer.writerow(
                    [
                        generation_index,
                        individual,
                        kge,
                        *[
                            params[name]
                            for name
                            in parameter_names
                        ],
                    ]
                )

    return csv_file


# ============================================================
# Main calibration
# ============================================================

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--basin",
        required=True,
    )

    parser.add_argument(
        "--workers",
        type=int,
        required=True,
    )

    parser.add_argument(
        "--population",
        type=int,
        default=DEFAULT_POPULATION,
    )

    parser.add_argument(
        "--generations",
        type=int,
        default=DEFAULT_GENERATIONS,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
    )

    args = parser.parse_args()

    if args.workers < 1:
        raise ValueError(
            "workers must be >= 1"
        )

    if args.population < 2:
        raise ValueError(
            "population must be >= 2"
        )

    print(
        "============================================================"
    )
    print(
        "PYMOO + COUPLED SUMMA-MIZUROUTE CALIBRATION"
    )
    print(
        "============================================================"
    )

    print(
        f"Basin       : {args.basin}"
    )

    print(
        f"Workers     : {args.workers}"
    )

    print(
        f"Population  : {args.population}"
    )

    print(
        f"Generations : {args.generations}"
    )

    print(
        f"Evaluations : approximately "
        f"{args.population * args.generations}"
    )

    print(
        f"Parameters  : {len(PARAMETERS)}"
    )

    print()

    for p in PARAMETERS:

        print(
            f"  {p['name']:24s} "
            f"{p['lower']:12g} "
            f"{p['upper']:12g} "
            f"{p['transform']}"
        )

    print()

    start = time.time()

    runtime_root, configs = (
        prepare_runtime(
            args.basin,
            args.workers,
        )
    )

    print(
        f"Runtime     : {runtime_root}"
    )

    print()

    context = mp.get_context(
        "spawn"
    )

    config_queue = context.Queue()

    for config in configs:
        config_queue.put(str(config))

    pool = context.Pool(
        processes=args.workers,
        initializer=initialize_worker,
        initargs=(config_queue,),
    )

    runner = StarmapParallelization(
        pool.starmap
    )

    try:

        problem = SummaCalibrationProblem(
            runner
        )

        algorithm = GA(
            pop_size=args.population,
            eliminate_duplicates=True,
        )

        result = minimize(
            problem,
            algorithm,
            termination=(
                "n_gen",
                args.generations,
            ),
            seed=args.seed,
            verbose=True,
            save_history=True,
        )

    finally:

        pool.close()
        pool.join()

    elapsed = time.time() - start

    best_x = np.asarray(
        result.X
    ).reshape(-1)

    best_params = decode_parameters(
        best_x
    )

    best_kge = -float(
        np.asarray(
            result.F
        ).reshape(-1)[0]
    )

    results_dir = (
        EXP5
        / "python_wrapper"
        / "results"
        / args.basin
    )

    history_file = write_history(
        result,
        args.basin,
        results_dir,
    )

    best_file = (
        results_dir
        / f"{args.basin}_pymoo_best.json"
    )

    summary = {
        "basin": args.basin,
        "optimizer": "pymoo_GA",
        "metric": "KGE",
        "workers": args.workers,
        "population": args.population,
        "generations": args.generations,
        "approx_evaluations":
            args.population
            * args.generations,
        "seed": args.seed,
        "elapsed_seconds": elapsed,
        "best_kge": best_kge,
        "best_parameters": best_params,
    }

    best_file.write_text(
        json.dumps(
            summary,
            indent=2,
        )
        + "\n"
    )

    print()
    print(
        "============================================================"
    )
    print(
        "CALIBRATION COMPLETE"
    )
    print(
        "============================================================"
    )

    print(
        f"Best KGE : {best_kge:.8f}"
    )

    print()

    for name, value in best_params.items():

        print(
            f"{name:24s} "
            f"{value:.12g}"
        )

    print()

    print(
        f"History  : {history_file}"
    )

    print(
        f"Best JSON: {best_file}"
    )

    print(
        f"Elapsed  : "
        f"{elapsed / 60.0:.2f} minutes"
    )


if __name__ == "__main__":
    main()