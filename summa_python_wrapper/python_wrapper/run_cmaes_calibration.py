#!/usr/bin/env python3
"""CMA-ES optimization using SUMMA's native Python/Fortran API."""

import argparse
import sys
from pathlib import Path

import numpy as np
import cma

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "pymoo_calibration"))

from calibration_config import load_calibration_config
from optimization_core import SummaEvaluator
from parameter_space import ParameterSpace
from summa_ctypes import SummaModel


def parse_args():
    p = argparse.ArgumentParser(
        description="SUMMA calibration with CMA-ES"
    )
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--library", type=Path, required=True)
    p.add_argument("--output-prefix", type=Path, required=True)

    p.add_argument("--n-evaluations", type=int, default=None)
    p.add_argument("--population-size", type=int, default=10)
    p.add_argument("--run-index", type=int, default=1)
    p.add_argument("--seed", type=int, default=1)

    p.add_argument(
        "--sigma",
        type=float,
        default=0.2,
        help="Initial CMA-ES step size in normalized coordinates",
    )

    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    config = load_calibration_config(args.config)

    budget = (
        args.n_evaluations
        if args.n_evaluations is not None
        else config["n_samples"]
    )

    if args.run_index < 1:
        raise ValueError("run-index must be positive")

    if args.population_size < 2:
        raise ValueError("population-size must be at least 2")

    if budget < args.population_size:
        raise ValueError(
            "Evaluation budget must be >= population size"
        )

    if budget % args.population_size != 0:
        raise ValueError(
            "For exact CMA-ES generation counting, "
            "evaluation budget must be divisible by population size"
        )

    if not 0 < args.sigma <= 1:
        raise ValueError("sigma must be within (0, 1]")

    run_seed = args.seed

    prefix = args.output_prefix.resolve()
    output = Path(str(prefix) + "_calibration.nc")

    print("Algorithm: cma_es")
    print("Configuration:", config["config_path"])
    print("Run index:", args.run_index)
    print("Seed:", run_seed)
    print("Evaluation budget:", budget)
    print("Population size:", args.population_size)
    print("Generations:", budget // args.population_size)
    print("Initial sigma:", args.sigma)
    print("Output:", output, flush=True)

    if args.dry_run:
        print("CMA-ES CONFIGURATION: PASS")
        return

    if not args.library.is_file():
        raise FileNotFoundError(args.library)

    if output.exists():
        raise FileExistsError(output)

    prefix.parent.mkdir(parents=True, exist_ok=True)

    model = None
    opened = False

    try:
        model = SummaModel(
            library_path=str(args.library.resolve()),
            config_path=str(config["config_path"]),
            run_index=args.run_index,
        )

        model.set_optimizer("cma_es")

        space = ParameterSpace(model.get_parameters())

        evaluator = SummaEvaluator(
            model=model,
            space=space,
            targets=config["targets"],
            budget=budget,
        )

        lower, upper = space.bounds()
        span = upper - lower

        # CMA-ES works in normalized coordinates [0, 1].
        # SUMMA receives transformed search coordinates,
        # converted to physical values by ParameterSpace.
        x0 = np.full(space.n_parameters, 0.5)

        options = {
            "bounds": [0.0, 1.0],
            "popsize": args.population_size,
            "seed": run_seed,
            "verbose": -9,
            "verb_disp": 0,
        }

        optimizer = cma.CMAEvolutionStrategy(
            x0,
            args.sigma,
            options,
        )

        model.output_open(
            path=str(output),
            n_trials=budget,
        )
        opened = True

        while evaluator.trial_count < budget:
            population = optimizer.ask()
            scores = []

            for candidate in population:
                normalized = np.clip(
                    np.asarray(candidate, dtype=float),
                    0.0,
                    1.0,
                )

                search = lower + normalized * span

                result = evaluator.evaluate_search(search)
                scores.append(result["scalar"])

            optimizer.tell(population, scores)

            print(
                f"generation={optimizer.countiter} "
                f"evaluations={evaluator.trial_count}/{budget} "
                f"best={evaluator.best_score:.8g}",
                flush=True,
            )

        model.output_close()
        opened = False

        if evaluator.best_physical is None:
            raise RuntimeError(
                "No successful SUMMA evaluation found"
            )

        best_path = Path(
            str(prefix)
            + f"_sample{evaluator.best_trial}_trialParams.nc"
        )

        model.export_best(
            path=str(best_path),
            trial=evaluator.best_trial,
            values=evaluator.best_physical,
        )

        print("========== CMA-ES COMPLETE ==========")
        print("Evaluations:", evaluator.trial_count)
        print("SUMMA simulations:", evaluator.simulation_count)
        print("Failed trials:", evaluator.failed_count)
        print("Best score:", evaluator.best_score)
        print("Calibration NetCDF:", output)
        print("Best parameters:", best_path)

    finally:
        if model is not None:
            try:
                if opened:
                    model.output_close()
            finally:
                model.finalize()


if __name__ == "__main__":
    main()
