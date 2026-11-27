#!/usr/bin/env python3
"""SPOTPY DDS and SCE-UA adapters for native SUMMA calibration."""

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import spotpy

WRAPPER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WRAPPER))
sys.path.insert(0, str(WRAPPER / "pymoo_calibration"))

from calibration_config import load_calibration_config
from optimization_core import SummaEvaluator, FAILURE_PENALTY
from parameter_space import ParameterSpace
from summa_ctypes import SummaModel


def run(algorithm="spotpy_dds"):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--output-prefix", type=Path, required=True)
    parser.add_argument("--n-evaluations", type=int, default=None)
    parser.add_argument("--run-index", type=int, default=1)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ngs", type=int, default=1)
    parser.add_argument("--kstop", type=int, default=100)
    parser.add_argument("--peps", type=float, default=0.001)
    parser.add_argument("--pcento", type=float, default=0.1)
    parser.add_argument("--perturbation-scale", type=float, default=0.2)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = load_calibration_config(args.config)
    budget = args.n_evaluations or config["n_samples"]
    seed = args.seed

    if budget < 5 or args.run_index < 1:
        parser.error("Invalid evaluation budget or run index")
    if args.ngs < 1 or args.kstop < 1:
        parser.error("ngs and kstop must be positive")
    if args.peps <= 0 or args.pcento <= 0:
        parser.error("peps and pcento must be positive")
    if not 0 < args.perturbation_scale <= 1:
        parser.error("Perturbation scale must be in (0, 1]")

    prefix = args.output_prefix.resolve()
    output = Path(str(prefix) + "_calibration.nc")

    print("Algorithm:", algorithm)
    print("Basin:", config["case_name"])
    print("Evaluations:", budget)
    print("Seed:", seed)
    if algorithm == "sceua":
        print("Complexes:", args.ngs)
        print("kstop:", args.kstop)
        print("peps:", args.peps)
        print("pcento:", args.pcento)
    print("Output:", output, flush=True)

    if args.dry_run:
        print("SPOTPY CONFIGURATION: PASS")
        return

    if output.exists():
        raise FileExistsError(output)

    if not args.library.is_file():
        raise FileNotFoundError(args.library)

    prefix.parent.mkdir(parents=True, exist_ok=True)

    random.seed(seed)
    np.random.seed(seed)

    model = None
    opened = False

    try:
        model = SummaModel(
            library_path=str(args.library.resolve()),
            config_path=str(config["config_path"]),
            run_index=args.run_index,
        )
        model.set_optimizer(algorithm)

        space = ParameterSpace(model.get_parameters())
        evaluator = SummaEvaluator(
            model, space, config["targets"], budget
        )

        lower, upper = map(np.asarray, space.bounds())

        if algorithm == "sceua":
            minimum = (2 * space.n_parameters + 1) * args.ngs
            if budget < minimum:
                raise ValueError(
                    f"SCE-UA requires at least {minimum} "
                    "evaluations for its initial population"
                )

        class Setup:
            def __init__(self):
                self.params = [
                    spotpy.parameter.Uniform(
                        f"z{i:03d}", 0.0, 1.0
                    )
                    for i in range(space.n_parameters)
                ]

            def parameters(self):
                return spotpy.parameter.generate(self.params)

            def simulation(self, vector):
                if evaluator.trial_count >= budget:
                    # Never run SUMMA beyond the requested budget.
                    # DDS maximizes, whereas SCE-UA minimizes.
                    penalty = (
                        -FAILURE_PENALTY
                        if algorithm == "spotpy_dds"
                        else FAILURE_PENALTY
                    )
                    return [penalty]

                z = np.asarray(vector, dtype=float)
                search = lower + z * (upper - lower)

                result = evaluator.evaluate_search(search)

                if evaluator.trial_count == 1 or \
                   evaluator.trial_count % 10 == 0:
                    print(
                        f"trial={evaluator.trial_count}/{budget} "
                        f"failed={result['failed']} "
                        f"best={evaluator.best_score:.8g}",
                        flush=True,
                    )

                # DDS maximizes; SCE-UA minimizes.
                value = result["scalar"]
                if algorithm == "spotpy_dds":
                    value = -value
                return [float(value)]

            def evaluation(self):
                return [0.0]

            def objectivefunction(self, simulation, evaluation):
                return float(simulation[0])

        setup = Setup()

        model.output_open(path=str(output), n_trials=budget)
        opened = True

        if algorithm == "spotpy_dds":
            sampler = spotpy.algorithms.dds(
                setup,
                dbformat="ram",
                save_sim=False,
                r=args.perturbation_scale,
            )
            sampler.sample(budget)
        else:
            sampler = spotpy.algorithms.sceua(
                setup,
                dbformat="ram",
                save_sim=False,
            )
            sampler.sample(
                budget,
                ngs=args.ngs,
                kstop=args.kstop,
                peps=args.peps,
                pcento=args.pcento,
            )

        model.output_close()
        opened = False

        if evaluator.best_physical is None:
            raise RuntimeError(
                "No successful SUMMA trial"
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

        print("Completed native trials:", evaluator.trial_count)
        print("SUMMA simulations:", evaluator.simulation_count)
        print("Failed trials:", evaluator.failed_count)
        print("Best score:", evaluator.best_score)
        print("Calibration NetCDF:", output)
        print("Best parameters:", best_path)
        print(algorithm.upper(), "COMPLETE")

    finally:
        if model is not None:
            try:
                if opened:
                    model.output_close()
            finally:
                model.finalize()


if __name__ == "__main__":
    run("spotpy_dds")
