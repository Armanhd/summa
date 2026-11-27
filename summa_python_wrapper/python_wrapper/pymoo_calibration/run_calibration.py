
#!/usr/bin/env python3
"""
SUMMA Python calibration using pymoo GA.

Uses the native SUMMA Fortran/C interface for:
- Parameter metadata and bounds
- Feasibility checks
- Simulation and objective evaluation
- Native calibration NetCDF output
- Export of the best physical parameter fields

No Ray, CSV, JSON, or hardcoded basin parameters.

This initial implementation runs one GA calibration per process.
Slurm will distribute independent basin/run processes.

IMPORTANT:
The native Fortran API must be updated to record the Python
optimizer name correctly before production runs.
"""

import argparse
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

from pymoo.algorithms.soo.nonconvex.ga import GA
from pymoo.operators.crossover.sbx import SBX
from pymoo.operators.mutation.pm import PM
from pymoo.core.problem import ElementwiseProblem
from pymoo.optimize import minimize

# Shared Python wrapper is one directory above this script.
WRAPPER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WRAPPER_DIR))

from summa_ctypes import SummaModel
from parameter_space import ParameterSpace
from calibration_config import load_calibration_config


FAILURE_PENALTY = 1.0e6


def time_components():
    """
    Return an 8-integer timestamp compatible with Fortran
    DATE_AND_TIME values.
    """
    now = datetime.now().astimezone()

    offset = now.utcoffset()
    utc_offset_minutes = (
        int(offset.total_seconds() / 60)
        if offset is not None else 0
    )

    return [
        now.year,
        now.month,
        now.day,
        utc_offset_minutes,
        now.hour,
        now.minute,
        now.second,
        now.microsecond // 1000,
    ]


def objective_score(objectives, targets):
    """
    Scalar objective for single-objective GA.

    KGE and NSE are maximized by SUMMA. pymoo minimizes F,
    so the optimization score is the weighted mean of
    (1 - efficiency).

    Targets with weight zero remain diagnostics and are
    recorded but do not influence GA selection.
    """
    if len(objectives) != len(targets):
        return FAILURE_PENALTY

    weighted_loss = 0.0
    total_weight = 0.0

    for value, target in zip(objectives, targets):
        weight = float(target.get("weight", 1.0))

        if weight <= 0:
            continue

        metric = str(target["metric"]).lower()

        if metric not in ("kge", "nse"):
            raise ValueError(
                f"GA objective conversion not yet defined "
                f"for metric: {metric}"
            )

        if not math.isfinite(float(value)):
            return FAILURE_PENALTY

        weighted_loss += weight * (1.0 - float(value))
        total_weight += weight

    if total_weight <= 0:
        raise ValueError("No positive-weight objectives")

    return weighted_loss / total_weight


def feasibility_result(result):
    """
    Interpret the shared SUMMA feasibility response.

    Accept either a boolean response or a mapping containing
    a feasibility flag.
    """
    if isinstance(result, (bool, np.bool_)):
        return bool(result)

    if isinstance(result, dict):
        for key in ("feasible", "is_feasible"):
            if key in result:
                return bool(result[key])

    raise RuntimeError(
        "Unexpected feasibility response from summa_ctypes.py: "
        f"{result!r}"
    )


class SummaGAProblem(ElementwiseProblem):
    """A single SUMMA calibration problem for pymoo GA."""

    def __init__(self, model, space, targets, budget):
        self.model = model
        self.space = space
        self.targets = targets
        self.budget = int(budget)

        self.trial_count = 0
        self.simulation_count = 0
        self.failed_count = 0

        self.best_score = float("inf")
        self.best_trial = None
        self.best_physical = None

        lower, upper = space.bounds()

        super().__init__(
            n_var=space.n_parameters,
            n_obj=1,
            xl=lower,
            xu=upper,
        )

    def _evaluate(self, x, out, *args, **kwargs):
        if self.trial_count >= self.budget:
            raise RuntimeError(
                "Evaluation budget exceeded"
            )

        trial = self.trial_count + 1

        physical = self.space.search_to_physical(x)
        start = datetime.now().astimezone()

        objectives = [float("nan")] * len(self.targets)
        failed = True

        feasible = feasibility_result(
            self.model.feasible(physical)
        )

        if feasible:
            self.simulation_count += 1

            result = self.model.evaluate(physical)

            returned = result.get("objectives", [])

            if (
                result.get("success", False)
                and not result.get("trial_failed", True)
                and len(returned) == len(self.targets)
            ):
                objectives = [
                    float(value) for value in returned
                ]
                failed = False

        if failed:
            score = FAILURE_PENALTY
            self.failed_count += 1
        else:
            score = objective_score(
                objectives, self.targets
            )

            if not math.isfinite(score):
                score = FAILURE_PENALTY
                failed = True
                self.failed_count += 1

        end = datetime.now().astimezone()

        # Native Fortran NetCDF writer.
        self.model.output_write(
            trial=trial,
            values=physical,
            objectives=objectives,
            failed=failed,
            start_time=start,
            end_time=end,
        )

        self.trial_count = trial

        if not failed and score < self.best_score:
            self.best_score = score
            self.best_trial = trial
            self.best_physical = physical.copy()

        out["F"] = float(score)

        if trial == 1 or trial % 100 == 0:
            print(
                f"trial={trial}/{self.budget} "
                f"simulations={self.simulation_count} "
                f"failed={self.failed_count} "
                f"best_score={self.best_score:.8g}",
                flush=True,
            )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Native SUMMA calibration with pymoo GA"
    )

    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Concrete SUMMA TOML configuration",
    )

    parser.add_argument(
        "--library",
        required=True,
        type=Path,
        help="Compiled SUMMA libsumma.so",
    )

    parser.add_argument(
        "--output-prefix",
        required=True,
        type=Path,
        help="Output prefix without .nc extension",
    )

    parser.add_argument(
        "--algorithm",
        default="ga",
        choices=["ga"],
    )

    parser.add_argument(
        "--n-evaluations",
        type=int,
        default=None,
        help="Override TOML calibration.n_samples",
    )

    parser.add_argument(
        "--population-size",
        type=int,
        default=100,
    )

    parser.add_argument(
        "--crossover-prob",
        type=float,
        default=0.9,
    )

    parser.add_argument(
        "--crossover-eta",
        type=float,
        default=15.0,
    )

    parser.add_argument(
        "--mutation-prob",
        type=float,
        default=0.1,
    )

    parser.add_argument(
        "--mutation-eta",
        type=float,
        default=20.0,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help="Base random seed",
    )

    parser.add_argument(
        "--run-index",
        type=int,
        default=1,
        help="Independent calibration run index, starting at 1",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate settings without initializing SUMMA",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    configuration = load_calibration_config(
        args.config
    )

    budget = (
        args.n_evaluations
        if args.n_evaluations is not None
        else configuration["n_samples"]
    )

    if args.run_index < 1:
        raise ValueError("run_index must be positive")

    run_seed = args.seed

    if budget <= 0:
        raise ValueError(
            "Evaluation budget must be positive"
        )

    if args.population_size < 2:
        raise ValueError(
            "GA population size must be at least 2"
        )

    if budget < args.population_size:
        raise ValueError(
            "Evaluation budget must be at least "
            "the population size"
        )

    # With a generation-based GA, restrict the initial
    # implementation to an exact whole-population budget.
    if budget % args.population_size != 0:
        raise ValueError(
            "For exact evaluation counting, "
            "--n-evaluations must be divisible "
            "by --population-size"
        )

    if not 0.0 <= args.crossover_prob <= 1.0:
        raise ValueError("Invalid crossover probability")

    if args.crossover_eta <= 0.0:
        raise ValueError("Crossover eta must be positive")

    if not 0.0 <= args.mutation_prob <= 1.0:
        raise ValueError("Invalid mutation probability")

    if args.mutation_eta <= 0.0:
        raise ValueError("Mutation eta must be positive")

    targets = configuration["targets"]

    for target in configuration["active_targets"]:
        if str(target["metric"]).lower() not in (
            "kge", "nse"
        ):
            raise ValueError(
                "Unsupported positive-weight GA objective: "
                + str(target["metric"])
            )

    output_prefix = args.output_prefix.resolve()
    calibration_path = Path(
        str(output_prefix) + "_calibration.nc"
    )

    print("========== SUMMA GA CONFIGURATION ==========")
    print("Config:", configuration["config_path"])
    print("Library:", args.library.resolve())
    print("Algorithm:", args.algorithm)
    print("Evaluation budget:", budget)
    print("Population size:", args.population_size)
    print("Crossover probability:", args.crossover_prob)
    print("Crossover eta:", args.crossover_eta)
    print("Mutation probability:", args.mutation_prob)
    print("Mutation eta:", args.mutation_eta)
    print("Nominal generations:", budget // args.population_size)
    print("Run index:", args.run_index)
    print("Seed:", run_seed)
    print("Targets:", len(targets))
    print(
        "Positive-weight targets:",
        len(configuration["active_targets"])
    )
    print("Native output:", calibration_path)

    if args.dry_run:
        print("DRY-RUN CONFIGURATION: PASS")
        print("SUMMA was not initialized")
        return

    if not args.library.is_file():
        raise FileNotFoundError(args.library)

    if calibration_path.exists():
        raise FileExistsError(calibration_path)

    calibration_path.parent.mkdir(
        parents=True, exist_ok=True
    )

    model = None
    output_open = False

    try:
        model = SummaModel(
            library_path=str(args.library.resolve()),
            config_path=str(
                configuration["config_path"]
            ),
            run_index=args.run_index,
        )

        # Record the actual Python optimization algorithm
        # in the native SUMMA calibration NetCDF file.
        # This does not change the scientific TOML settings.
        model.set_optimizer(args.algorithm)

        parameters = model.get_parameters()
        space = ParameterSpace(parameters)

        print(
            "Native SUMMA parameters:",
            space.n_parameters
        )

        problem = SummaGAProblem(
            model=model,
            space=space,
            targets=targets,
            budget=budget,
        )

        model.output_open(
            path=str(calibration_path),
            n_trials=budget,
        )
        output_open = True

        algorithm = GA(
            pop_size=args.population_size,
            crossover=SBX(
                prob=args.crossover_prob,
                eta=args.crossover_eta,
            ),
            mutation=PM(
                prob=1.0,
                prob_var=args.mutation_prob,
                eta=args.mutation_eta,
            ),
            eliminate_duplicates=False,
        )

        minimize(
            problem,
            algorithm,
            termination=("n_eval", budget),
            seed=run_seed,
            verbose=False,
            save_history=False,
        )

        if problem.trial_count != budget:
            raise RuntimeError(
                "GA did not consume exactly the "
                "requested evaluation budget: "
                f"{problem.trial_count} != {budget}"
            )

        model.output_close()
        output_open = False

        if problem.best_physical is None:
            raise RuntimeError(
                "No successful model evaluation "
                "was found"
            )

        best_path = Path(
            str(output_prefix)
            + f"_sample{problem.best_trial}_trialParams.nc"
        )

        model.export_best(
            path=str(best_path),
            trial=problem.best_trial,
            values=problem.best_physical,
        )

        print("========== GA COMPLETE ==========")
        print("Evaluations:", problem.trial_count)
        print("Model simulations:", problem.simulation_count)
        print("Failed trials:", problem.failed_count)
        print("Best score:", problem.best_score)
        print("Best trial:", problem.best_trial)
        print("Calibration NetCDF:", calibration_path)
        print("Best parameters:", best_path)

    finally:
        if model is not None:
            if output_open:
                model.output_close()
            model.finalize()


if __name__ == "__main__":
    main()
