#!/usr/bin/env python3
"""Custom DDS using the existing candidate generator and native SUMMA API."""

import argparse
import random
import sys
from pathlib import Path

import numpy as np

WRAPPER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WRAPPER))
sys.path.insert(0, str(WRAPPER / "pymoo_calibration"))

from dds_optimiser import dds_candidate
from calibration_config import load_calibration_config
from optimization_core import SummaEvaluator
from parameter_space import ParameterSpace
from summa_ctypes import SummaModel


def main():
    parser = argparse.ArgumentParser(
        description="Native SUMMA custom Python DDS"
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--n-evaluations", type=int, default=None)
    parser.add_argument("--run-index", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--perturbation-scale", type=float, default=0.2)
    parser.add_argument(
        "--boundary-method",
        choices=("reflect", "reject"),
        default="reflect",
    )
    parser.add_argument("--max-attempts", type=int, default=50000)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_calibration_config(args.config)
    budget = (
        args.n_evaluations
        if args.n_evaluations is not None
        else config["n_samples"]
    )

    if budget < 2:
        parser.error("DDS requires at least two evaluations")
    if args.run_index < 1 or args.max_attempts < 1:
        parser.error("Invalid run index or max attempts")
    if not 0 < args.perturbation_scale <= 1:
        parser.error("Perturbation scale must be in (0, 1]")

    seed = args.seed + args.run_index - 1
    prefix = args.output_prefix.resolve()
    output = Path(str(prefix) + "_calibration.nc")

    print("Algorithm: custom_dds")
    print("Case:", config["case_name"])
    print("Evaluations:", budget)
    print("Seed:", seed)
    print("Boundary:", args.boundary_method)
    print("Perturbation scale:", args.perturbation_scale)
    print("Output:", output, flush=True)

    if args.dry_run:
        print("CUSTOM DDS CONFIGURATION: PASS")
        return

    if output.exists():
        raise FileExistsError(output)

    prefix.parent.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    model = None
    opened = False

    try:
        model = SummaModel(
            library_path=str(args.library.resolve()),
            config_path=str(config["config_path"]),
            run_index=args.run_index,
        )
        model.set_optimizer("custom_dds")

        space = ParameterSpace(model.get_parameters())
        evaluator = SummaEvaluator(
            model, space, config["targets"], budget
        )

        lower, upper = space.bounds()
        span = np.asarray(upper) - np.asarray(lower)

        best_z = None

        model.output_open(path=str(output), n_trials=budget)
        opened = True

        while evaluator.trial_count < budget:
            trial = evaluator.trial_count + 1

            for attempt in range(1, args.max_attempts + 1):
                if best_z is None:
                    z = [rng.random() for _ in range(space.n_parameters)]
                else:
                    z = dds_candidate(
                        best_z,
                        trial,
                        budget,
                        rng,
                        args.perturbation_scale,
                        args.boundary_method,
                    )

                if z is None:
                    continue

                search = np.asarray(lower) + np.asarray(z) * span
                physical = space.search_to_physical(search)

                if model.feasible(physical):
                    break
            else:
                raise RuntimeError(
                    f"No feasible DDS candidate after "
                    f"{args.max_attempts} attempts"
                )

            result = evaluator.evaluate_search(search)

            if not result["failed"] and evaluator.best_trial == trial:
                best_z = list(z)

            print(
                f"trial={trial}/{budget} "
                f"failed={result['failed']} "
                f"attempts={attempt} "
                f"best={evaluator.best_score:.8g}",
                flush=True,
            )

        model.output_close()
        opened = False

        if evaluator.best_physical is None:
            raise RuntimeError("No successful SUMMA trial")

        best_path = Path(
            str(prefix)
            + f"_sample{evaluator.best_trial}_trialParams.nc"
        )

        model.export_best(
            path=str(best_path),
            trial=evaluator.best_trial,
            values=evaluator.best_physical,
        )

        print("Calibration NetCDF:", output)
        print("Best parameter NetCDF:", best_path)
        print("CUSTOM DDS: COMPLETE")

    finally:
        if model is not None:
            try:
                if opened:
                    model.output_close()
            finally:
                model.finalize()


if __name__ == "__main__":
    main()
