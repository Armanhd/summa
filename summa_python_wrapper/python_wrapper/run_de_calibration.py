#!/usr/bin/env python3
"""SciPy Differential Evolution calibration using the native SUMMA API."""

import argparse
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pymoo_calibration"))

from calibration_config import load_calibration_config
from optimization_core import SummaEvaluator
from parameter_space import ParameterSpace
from summa_ctypes import SummaModel


class BudgetReached(Exception):
    """Stop DE after the exact requested number of trial evaluations."""


def arguments():
    p = argparse.ArgumentParser(
        description="SUMMA calibration with SciPy Differential Evolution"
    )
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--library", type=Path, required=True)
    p.add_argument("--output-prefix", type=Path, required=True)
    p.add_argument("--n-evaluations", type=int, default=None)
    p.add_argument("--population-size", type=int, default=40)
    p.add_argument("--run-index", type=int, default=1)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--strategy", default="best1bin")
    p.add_argument("--mutation", type=float, default=0.8)
    p.add_argument("--crossover", type=float, default=0.7)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = arguments()
    config = load_calibration_config(args.config)

    budget = (
        args.n_evaluations
        if args.n_evaluations is not None
        else config["n_samples"]
    )

    if args.run_index < 1:
        raise ValueError("run-index must be positive")

    if args.population_size < 5:
        raise ValueError("DE population size must be at least 5")

    if budget < args.population_size:
        raise ValueError(
            "Evaluation budget must be >= population size"
        )

    if not 0 <= args.crossover <= 1:
        raise ValueError("Crossover must be between 0 and 1")

    if not 0 <= args.mutation < 2:
        raise ValueError("Mutation must be between 0 and 2")

    run_seed = args.seed

    prefix = args.output_prefix.resolve()
    output = Path(str(prefix) + "_calibration.nc")

    print("Algorithm: differential_evolution")
    print("Configuration:", config["config_path"])
    print("Run index:", args.run_index)
    print("Seed:", run_seed)
    print("Evaluation budget:", budget)
    print("Population:", args.population_size)
    print("Strategy:", args.strategy)
    print("Mutation:", args.mutation)
    print("Crossover:", args.crossover)
    print("Output:", output, flush=True)

    if args.dry_run:
        print("DE CONFIGURATION: PASS")
        return

    if output.exists():
        raise FileExistsError(output)

    if not args.library.is_file():
        raise FileNotFoundError(args.library)

    prefix.parent.mkdir(parents=True, exist_ok=True)

    model = None
    opened = False

    try:
        model = SummaModel(
            library_path=str(args.library.resolve()),
            config_path=str(config["config_path"]),
            run_index=args.run_index,
        )

        model.set_optimizer("differential_evolution")

        space = ParameterSpace(model.get_parameters())

        evaluator = SummaEvaluator(
            model=model,
            space=space,
            targets=config["targets"],
            budget=budget,
        )

        lower, upper = space.bounds()
        bounds = list(zip(lower, upper))

        rng = np.random.default_rng(run_seed)

        initial_population = rng.uniform(
            lower,
            upper,
            size=(args.population_size, space.n_parameters),
        )

        model.output_open(
            path=str(output),
            n_trials=budget,
        )
        opened = True

        def objective(x):
            if evaluator.trial_count >= budget:
                raise BudgetReached()

            result = evaluator.evaluate_search(x)
            return result["scalar"]

        try:
            differential_evolution(
                objective,
                bounds=bounds,
                strategy=args.strategy,
                mutation=args.mutation,
                recombination=args.crossover,
                init=initial_population,
                maxiter=budget,
                polish=False,
                seed=run_seed,
                workers=1,
                updating="immediate",
                disp=False,
            )
        except BudgetReached:
            pass

        print("Evaluations:", evaluator.trial_count)
        print("SUMMA simulations:", evaluator.simulation_count)
        print("Failed trials:", evaluator.failed_count)

        model.output_close()
        opened = False

        if evaluator.best_physical is None:
            raise RuntimeError("No successful SUMMA evaluation")

        best_path = Path(
            str(prefix)
            + f"_sample{evaluator.best_trial}_trialParams.nc"
        )

        model.export_best(
            path=str(best_path),
            trial=evaluator.best_trial,
            values=evaluator.best_physical,
        )

        print("Best score:", evaluator.best_score)
        print("Calibration output:", output)
        print("Best parameter output:", best_path)
        print("DE CALIBRATION: COMPLETE")

    finally:
        if model is not None:
            try:
                if opened:
                    model.output_close()
            finally:
                model.finalize()


if __name__ == "__main__":
    main()
