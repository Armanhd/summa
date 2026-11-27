import os
import multiprocessing as mp
from pathlib import Path

import numpy as np

from pymoo.core.problem import ElementwiseProblem
from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.optimize import minimize
from pymoo.parallelization.starmap import StarmapParallelization

import sys

WRAPPER_DIR = Path(
    "/work/comphyd_lab/users/arman.haddadchi/"
    "hydro_models/summa_v4.5_python/python_wrapper"
)

sys.path.insert(0, str(WRAPPER_DIR))

from summa_ctypes import SummaModel


# ============================================================
# Configuration
# ============================================================

NWORKERS = 4

LIB = (
    "/work/comphyd_lab/users/arman.haddadchi/"
    "hydro_models/builds/"
    "summa_v4.5_python_coupled/libsumma.so"
)

RUNTIME = Path(
    "/work/comphyd_lab/users/arman.haddadchi/"
    "CENTURY_Basins_summa_mizuroute_exps/"
    "Exp5_coupledsumma_hourly_Newdata/"
    "python_wrapper/runtime/CAN_01AD003"
)


PARAM_NAMES = [
    "k_soil",
    "aquiferScaleFactor",
    "aquiferBaseflowExp",
    "qSurfScale",
    "Fcapil",
    "tempCritRain",
]


LOWER = np.array([
    1.0e-7,
    0.1,
    1.0,
    1.0,
    0.01,
    272.16,
])


UPPER = np.array([
    1.0e-5,
    100.0,
    10.0,
    100.0,
    0.10,
    274.16,
])


# ============================================================
# One persistent SUMMA model per worker process
# ============================================================

_worker_model = None
_worker_id = None


def initialize_worker(config_queue):

    global _worker_model
    global _worker_id

    config_path = config_queue.get()

    _worker_id = Path(config_path).parent.name

    # Initialize SUMMA once for this process.
    _worker_model = SummaModel(
        library_path=LIB,
        config_path=config_path,
    )

    # SUMMA is very verbose. Suppress Fortran/Python worker output
    # after successful initialization to avoid large log files.
    devnull = os.open(os.devnull, os.O_WRONLY)

    os.dup2(devnull, 1)
    os.dup2(devnull, 2)

    os.close(devnull)


# ============================================================
# Pymoo problem
# ============================================================

class SummaProblem(ElementwiseProblem):

    def __init__(self, **kwargs):

        super().__init__(
            n_var=len(PARAM_NAMES),
            n_obj=1,
            xl=LOWER,
            xu=UPPER,
            **kwargs,
        )

    def _evaluate(self, x, out, *args, **kwargs):

        params = dict(zip(PARAM_NAMES, x))

        kge = _worker_model.evaluate(params)

        # Pymoo minimizes.
        out["F"] = -kge


# ============================================================
# Main
# ============================================================

def main():

    print("====================================================")
    print("PYMOO + SUMMA PARALLEL SMOKE TEST")
    print("====================================================")
    print(f"Workers    : {NWORKERS}")
    print("Population : 4")
    print("Generations: 2")
    print()

    configs = [
        str(RUNTIME / f"worker_{i:02d}" / "config.toml")
        for i in range(NWORKERS)
    ]

    for config in configs:
        if not Path(config).is_file():
            raise FileNotFoundError(config)

    # Spawn gives every worker a clean process/address space,
    # important because libsumma contains persistent Fortran state.
    ctx = mp.get_context("spawn")

    config_queue = ctx.Queue()

    for config in configs:
        config_queue.put(config)

    pool = ctx.Pool(
        processes=NWORKERS,
        initializer=initialize_worker,
        initargs=(config_queue,),
    )

    runner = StarmapParallelization(pool.starmap)

    try:

        problem = SummaProblem(
            elementwise_runner=runner
        )

        algorithm = GA(
            pop_size=4,
            eliminate_duplicates=True,
        )

        result = minimize(
            problem,
            algorithm,
            termination=("n_gen", 2),
            seed=1,
            verbose=True,
        )

    finally:

        pool.close()
        pool.join()

    print()
    print("====================================================")
    print("PARALLEL PYMOO TEST COMPLETE")
    print("====================================================")

    print("Best parameters:")

    for name, value in zip(PARAM_NAMES, result.X):
        print(f"{name:24s} {value:.12g}")

    print()
    print("Best KGE:", -float(result.F))


if __name__ == "__main__":
    main()