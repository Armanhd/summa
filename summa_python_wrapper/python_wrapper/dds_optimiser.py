#!/usr/bin/env python3
"""
Python DDS optimiser for SUMMA.

SUMMA handles model parameters, physical constraints, simulations,
routing, and objective-function calculations.

Python handles DDS candidate generation, trial scheduling, tracking
the best solution, and saving calibration results.

DDS implementation notes
------------------------
1. Initialization:
   With random initialization, this implementation starts DDS
   perturbations as soon as the first successful simulation
   establishes a best solution.

   Unlike SPOTPY DDS, it does not reserve a fixed initial random
   sampling phase. SPOTPY uses at least 5 initial evaluations,
   or approximately 0.5% of the total evaluation budget.

2. Parameter boundaries:
   The default method is 100% reflection. If a proposed parameter
   exceeds its bounds, it is reflected back into the allowed range.
   Large overshoots are handled through repeated reflection.

   This differs from SPOTPY DDS, which randomly chooses between
   reflection (50%) and absorption (50%) when a bound is violated.
   Absorption places the parameter exactly on the violated bound.

3. Parameter space:
   DDS operates on normalized coordinates between 0 and 1.
   Parameters are converted back to physical values before SUMMA
   checks feasibility and runs the model.

4. Feasibility:
   Candidates that violate additional SUMMA physical constraints
   are rejected and regenerated, even after boundary reflection.

References
----------
Tolson and Shoemaker (2007), Water Resources Research.
DOI: 10.1029/2005WR004723

SPOTPY DDS:
https://github.com/thouska/spotpy/blob/master/src/spotpy/algorithms/dds.py

One persistent SUMMA instance per Python process.

"""

import argparse
import csv
import ctypes as C
import json
import math
import random
import sys
import tomllib
from datetime import datetime, timezone
from pathlib import Path


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, data):
    # Replace a completed JSON file atomically.
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


class SummaWorker:
    def __init__(self, library):
        self.lib = C.CDLL(str(Path(library).resolve()))
        self.initialized = False

        lib = self.lib

        lib.summa_py_init.argtypes = [
            C.c_char_p, C.POINTER(C.c_char), C.c_int]
        lib.summa_py_init.restype = C.c_int

        lib.summa_py_finalize.argtypes = []
        lib.summa_py_finalize.restype = C.c_int

        lib.summa_py_nparameters.argtypes = []
        lib.summa_py_nparameters.restype = C.c_int

        lib.summa_py_get_parameter.argtypes = [
            C.c_int,
            C.POINTER(C.c_char), C.c_int,
            C.POINTER(C.c_char), C.c_int,
            C.POINTER(C.c_double), C.POINTER(C.c_double),
            C.POINTER(C.c_double), C.POINTER(C.c_double),
        ]
        lib.summa_py_get_parameter.restype = C.c_int

        lib.summa_py_check_feasibility.argtypes = [
            C.c_int, C.POINTER(C.c_double),
            C.POINTER(C.c_int), C.POINTER(C.c_char), C.c_int
        ]
        lib.summa_py_check_feasibility.restype = C.c_int

        lib.summa_py_evaluate.argtypes = [
            C.c_int, C.POINTER(C.c_double), C.c_int,
            C.POINTER(C.c_double),
            C.POINTER(C.c_int), C.POINTER(C.c_int),
            C.POINTER(C.c_char), C.c_int
        ]
        lib.summa_py_evaluate.restype = C.c_int

        lib.summa_py_get_defaults.argtypes = [
            C.c_int, C.POINTER(C.c_double),
            C.POINTER(C.c_char), C.c_int
        ]
        lib.summa_py_get_defaults.restype = C.c_int

        lib.summa_py_output_open.argtypes = [
            C.c_char_p, C.c_int, C.POINTER(C.c_char), C.c_int
        ]
        lib.summa_py_output_open.restype = C.c_int

        lib.summa_py_output_write.argtypes = [
            C.c_int, C.c_int, C.POINTER(C.c_double),
            C.c_int, C.POINTER(C.c_double), C.c_int,
            C.POINTER(C.c_int), C.POINTER(C.c_int),
            C.POINTER(C.c_char), C.c_int
        ]
        lib.summa_py_output_write.restype = C.c_int

        lib.summa_py_output_close.argtypes = [
            C.POINTER(C.c_char), C.c_int
        ]
        lib.summa_py_output_close.restype = C.c_int

        lib.summa_py_export_best.argtypes = [
            C.c_char_p, C.c_int, C.c_int,
            C.POINTER(C.c_double),
            C.POINTER(C.c_char), C.c_int
        ]
        lib.summa_py_export_best.restype = C.c_int

        self.output_opened = False
        self.parameters = []

    def initialise(self, config):
        message = C.create_string_buffer(4096)
        rc = self.lib.summa_py_init(
            str(Path(config).resolve()).encode(),
            message,
            len(message),
        )
        if rc:
            raise RuntimeError(
                f"SUMMA initialisation failed ({rc}): "
                f"{message.value.decode(errors='replace')}"
            )

        self.initialized = True
        self.parameters = self.get_parameters()

    def get_parameters(self):
        n = self.lib.summa_py_nparameters()
        if n <= 0:
            raise RuntimeError("No calibration parameters returned")

        parameters = []

        for index in range(1, n + 1):
            name = C.create_string_buffer(128)
            transform = C.create_string_buffer(64)

            lower = C.c_double()
            upper = C.c_double()
            search_lower = C.c_double()
            search_upper = C.c_double()

            rc = self.lib.summa_py_get_parameter(
                index,
                name, len(name),
                transform, len(transform),
                C.byref(lower), C.byref(upper),
                C.byref(search_lower), C.byref(search_upper),
            )

            if rc:
                raise RuntimeError(
                    f"Failed to retrieve parameter {index}"
                )

            entry = {
                "name": name.value.decode(),
                "transform": transform.value.decode().strip().lower(),
                "lower": lower.value,
                "upper": upper.value,
                "search_lower": search_lower.value,
                "search_upper": search_upper.value,
            }

            if entry["transform"] not in ("none", "log"):
                raise ValueError(
                    f"Unsupported transformation: {entry}"
                )

            for key in (
                "lower", "upper", "search_lower", "search_upper"
            ):
                if not math.isfinite(entry[key]):
                    raise ValueError(
                        f"Non-finite parameter metadata: {entry}"
                    )

            if not entry["search_lower"] < entry["search_upper"]:
                raise ValueError(
                    f"Invalid parameter search bounds: {entry}"
                )

            if entry["transform"] == "log" and entry["lower"] <= 0:
                raise ValueError(
                    f"Log parameter must be positive: {entry}"
                )

            parameters.append(entry)

        return parameters

    def feasible(self, physical):
        n = len(physical)
        x = (C.c_double * n)(*physical)

        accepted = C.c_int(0)
        message = C.create_string_buffer(4096)

        rc = self.lib.summa_py_check_feasibility(
            n, x, C.byref(accepted), message, len(message)
        )

        if rc:
            raise RuntimeError(
                f"Native feasibility error ({rc}): "
                f"{message.value.decode(errors='replace')}"
            )

        return bool(accepted.value)

    def evaluate(self, physical):
        n = len(physical)
        x = (C.c_double * n)(*physical)

        values = (C.c_double * 32)()
        nout = C.c_int(0)
        failed = C.c_int(1)
        message = C.create_string_buffer(4096)

        rc = self.lib.summa_py_evaluate(
            n, x, 32, values,
            C.byref(nout), C.byref(failed),
            message, len(message),
        )

        objectives = [values[i] for i in range(nout.value)]

        success = (
            rc == 0
            and failed.value == 0
            and len(objectives) >= 1
            and all(math.isfinite(v) for v in objectives)
        )

        return {
            "success": success,
            "objectives": objectives,
            "error_code": rc,
            "trial_failed": bool(failed.value),
            "message": message.value.decode(errors="replace"),
        }


    def get_defaults(self):
        n = len(self.parameters)
        values = (C.c_double * n)()
        message = C.create_string_buffer(4096)

        rc = self.lib.summa_py_get_defaults(
            n, values, message, len(message)
        )
        if rc:
            raise RuntimeError(
                f"Native defaults failed ({rc}): "
                f"{message.value.decode(errors='replace')}"
            )
        return list(values)

    def output_open(self, path, n_trials):
        message = C.create_string_buffer(4096)
        rc = self.lib.summa_py_output_open(
            str(path).encode(), n_trials, message, len(message)
        )
        if rc:
            raise RuntimeError(
                f"Native NetCDF creation failed ({rc}): "
                f"{message.value.decode(errors='replace')}"
            )
        self.output_opened = True

    def output_write(self, trial, physical, result, start, end):
        n = len(physical)
        objectives = result["objectives"]
        nobj = len(objectives)

        if not result["success"]:
            # The native writer fills failed-trial objectives.
            # The native target count for this validated case is three.
            objectives = [0.0, 0.0, 0.0]
            nobj = 3

        x = (C.c_double * n)(*physical)
        y = (C.c_double * nobj)(*objectives)

        def components(dt):
            return (C.c_int * 8)(
                dt.year, dt.month, dt.day, 0,
                dt.hour, dt.minute, dt.second,
                dt.microsecond // 1000
            )

        message = C.create_string_buffer(4096)

        rc = self.lib.summa_py_output_write(
            trial, n, x, nobj, y,
            int(not result["success"]),
            components(start), components(end),
            message, len(message)
        )
        if rc:
            raise RuntimeError(
                f"Native trial write failed ({rc}): "
                f"{message.value.decode(errors='replace')}"
            )

    def output_close(self):
        if not self.output_opened:
            return

        message = C.create_string_buffer(4096)
        rc = self.lib.summa_py_output_close(
            message, len(message)
        )
        if rc:
            raise RuntimeError(
                f"Native NetCDF close failed ({rc}): "
                f"{message.value.decode(errors='replace')}"
            )
        self.output_opened = False

    def export_best(self, path, trial, physical):
        n = len(physical)
        x = (C.c_double * n)(*physical)
        message = C.create_string_buffer(4096)

        rc = self.lib.summa_py_export_best(
            str(path).encode(), trial, n, x,
            message, len(message)
        )
        if rc:
            raise RuntimeError(
                f"Native physical parameter export failed ({rc}): "
                f"{message.value.decode(errors='replace')}"
            )

    def finalize(self):
        self.output_close()
        if self.lib is None:
            return

        rc = self.lib.summa_py_finalize()

        if rc:
            raise RuntimeError(f"MPI finalization failed: {rc}")

        self.initialized = False
        print("MPI finalization status: 0", flush=True)


def physical_from_normalized(z, parameters):
    """
    DDS works in [0,1]^d search coordinates.
    SUMMA receives physical parameter values.
    """
    result = []

    for u, p in zip(z, parameters):
        search_value = (
            p["search_lower"]
            + u * (p["search_upper"] - p["search_lower"])
        )

        if p["transform"] == "log":
            physical = math.exp(search_value)
        else:
            physical = search_value

        result.append(physical)

    return result



def normalized_from_physical(physical, parameters):
    if len(physical) != len(parameters):
        raise ValueError("Incorrect default parameter count")

    coordinates = []

    for value, p in zip(physical, parameters):
        if p["transform"] == "log":
            if value <= 0:
                raise ValueError(
                    f"Nonpositive default: {p['name']}"
                )
            search_value = math.log(value)
        else:
            search_value = value

        lower = p["search_lower"]
        upper = p["search_upper"]
        u = (search_value - lower) / (upper - lower)

        bounded_u = min(1.0, max(0.0, u))

        if not 0.0 <= u <= 1.0:
            bounded_value = physical_from_normalized(
                [bounded_u], [p]
            )[0]
            print(
                f"BOUNDED DEFAULT: {p['name']}: "
                f"{value} -> {bounded_value}",
                flush=True,
            )

        coordinates.append(bounded_u)

    return coordinates


def reflect01(value):
    """Reflect a perturbed coordinate at the [0,1] boundaries."""
    value = value % 2.0
    return value if value <= 1.0 else 2.0 - value


def dds_candidate(
    best, trial_index, n_trials, rng,
    scale=0.2, boundary_method="reflect"
):
    """
    Generate one conventional DDS proposal in normalized search space.

    reflect: Reflect coordinates into [0, 1].
    reject:  Reject the entire proposal if any coordinate is out of bounds.
    """
    d = len(best)

    probability = 1.0 - math.log(trial_index) / math.log(n_trials)
    probability = max(0.0, min(1.0, probability))

    selected = [
        j for j in range(d)
        if rng.random() < probability
    ]

    if not selected:
        selected = [rng.randrange(d)]

    proposal = best.copy()

    for j in selected:
        candidate = best[j] + rng.gauss(0.0, scale)

        if boundary_method == "reject":
            if not 0.0 <= candidate <= 1.0:
                return None
            proposal[j] = candidate

        elif boundary_method == "reflect":
            proposal[j] = reflect01(candidate)

        else:
            raise ValueError(
                f"Unknown boundary method: {boundary_method}"
            )

    return proposal


def generate_feasible(worker, generator, max_attempts):
    """Reject infeasible proposals using native SUMMA checks."""
    for attempt in range(1, max_attempts + 1):
        z = generator()

        if z is None:
            continue

        physical = physical_from_normalized(z, worker.parameters)

        if worker.feasible(physical):
            return z, physical, attempt

    raise RuntimeError(
        f"No feasible candidate after {max_attempts} proposals"
    )


def run_dds(worker, args):
    rng = random.Random(args.seed)

    output_dir = Path(args.results_dir).resolve()

    # Do not overwrite a previous calibration.
    output_dir.mkdir(parents=True, exist_ok=False)

    history_path = output_dir / "dds_history.csv"
    best_path = output_dir / "dds_best.json"
    metadata_path = output_dir / "dds_metadata.json"

    parameters = worker.parameters
    nparam = len(parameters)
    names = [p["name"] for p in parameters]

    if args.expected_parameters is not None:
        if nparam != args.expected_parameters:
            raise RuntimeError(
                f"Expected {args.expected_parameters} parameters, "
                f"received {nparam}"
            )

    write_json(metadata_path, {
        "created_utc": timestamp(),
        "algorithm": "conventional_python_dds",
        "native_pr675_exact_reproduction": False,
        "config": str(Path(args.config).resolve()),
        "library": str(Path(args.library).resolve()),
        "seed": args.seed,
        "start_method": args.start,
        "boundary_method": args.boundary_method,
        "n_trials": args.n_trials,
        "perturbation_scale": args.perturbation_scale,
        "objective_selection": "first_native_objective",
        "objective_direction": "maximize",
        "parameters": parameters,
    })

    fields = (
        ["trial", "success", "objective_1", "objective_2",
         "objective_3", "best_kge", "is_new_best",
         "feasibility_attempts", "error_code", "message"]
        + [f"param_{name}" for name in names]
    )

    default_z = None

    if args.start == "defaults":
        defaults = worker.get_defaults()
        default_z = normalized_from_physical(
            defaults, parameters
        )
        bounded_defaults = physical_from_normalized(
            default_z, parameters
        )

        if not worker.feasible(bounded_defaults):
            raise RuntimeError(
                "Bounded SUMMA defaults fail native feasibility. "
                "Check the configured physical constraints."
            )

    native_prefix = (
        f"CAN_01AD003_run{args.run_index:04d}"
    )
    calibration_nc = output_dir / (
        native_prefix + "_calibration.nc"
    )

    worker.output_open(calibration_nc, args.n_trials)

    best_kge = -math.inf
    best_z = None
    best_physical = None
    best_objectives = None
    best_trial = None

    with history_path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        stream.flush()

        for trial in range(1, args.n_trials + 1):

            if best_z is None:
                if args.start == "defaults":
                    generator = lambda: default_z.copy()
                else:
                    generator = lambda: [
                        rng.random() for _ in range(nparam)
                    ]

            else:
                generator = lambda: dds_candidate(
                    best_z, trial, args.n_trials, rng,
                    args.perturbation_scale,
                    args.boundary_method
                )

            z, physical, attempts = generate_feasible(
                worker, generator, args.max_attempts
            )

            start_time = datetime.now(timezone.utc)
            result = worker.evaluate(physical)
            end_time = datetime.now(timezone.utc)

            worker.output_write(
                trial, physical, result, start_time, end_time
            )

            objectives = result["objectives"]
            success = result["success"]

            kge = objectives[0] if success else float("nan")

            improved = success and kge > best_kge

            if improved:
                best_kge = kge
                best_z = z.copy()
                best_physical = physical.copy()
                best_objectives = objectives.copy()
                best_trial = trial

            row = {
                "trial": trial,
                "success": int(success),
                "objective_1": objectives[0] if len(objectives) > 0 else "",
                "objective_2": objectives[1] if len(objectives) > 1 else "",
                "objective_3": objectives[2] if len(objectives) > 2 else "",
                "best_kge": best_kge if best_z is not None else "",
                "is_new_best": int(improved),
                "feasibility_attempts": attempts,
                "error_code": result["error_code"],
                "message": result["message"].replace("\n", " "),
            }

            row.update({
                f"param_{name}": value
                for name, value in zip(names, physical)
            })

            writer.writerow(row)
            stream.flush()

            if best_z is not None:
                write_json(best_path, {
                    "updated_utc": timestamp(),
                    "best_trial": best_trial,
                    "best_kge": best_kge,
                    "objectives": best_objectives,
                    "parameters": dict(zip(names, best_physical)),
                    "normalized_search_coordinates": best_z,
                    "completed_trials": trial,
                    "seed": args.seed,
                    "config": str(Path(args.config).resolve()),
                })

            print(
                f"DDS trial {trial:03d}/{args.n_trials}: "
                f"success={success}, "
                f"KGE={kge:.8f}, "
                f"best={best_kge:.8f}, "
                f"new_best={improved}, "
                f"feasibility_attempts={attempts}",
                flush=True,
            )

    if best_z is None:
        raise RuntimeError(
            "DDS finished without a successful SUMMA evaluation"
        )

    worker.output_close()

    best_params_nc = output_dir / (
        native_prefix
        + f"_sample{best_trial}_trialParams.nc"
    )
    worker.export_best(
        best_params_nc, best_trial, best_physical
    )

    print("Native calibration NetCDF:", calibration_nc, flush=True)
    print("Native best parameter NetCDF:", best_params_nc, flush=True)

    print("\n========== DDS SUMMARY ==========", flush=True)
    print("Number of trials:", args.n_trials, flush=True)
    print("Best trial:", best_trial, flush=True)
    print("Best KGE:", best_kge, flush=True)
    print("Best objectives:", best_objectives, flush=True)
    print("History:", history_path, flush=True)
    print("Best parameters:", best_path, flush=True)
    print("DDS CALIBRATION: PASS", flush=True)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("--library", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--results-dir", required=True)

    parser.add_argument("--n-trials", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--run-index", type=int, default=1)

    parser.add_argument(
        "--start",
        choices=("random", "defaults"),
        default="random",
    )

    parser.add_argument(
        "--boundary-method",
        choices=("reflect", "reject"),
        default="reflect",
    )
    parser.add_argument(
        "--expected-parameters", type=int, default=None
    )
    parser.add_argument(
        "--perturbation-scale", type=float, default=0.2
    )
    parser.add_argument(
        "--max-attempts", type=int, default=1000
    )

    args = parser.parse_args()

    # SUMMA TOML remains authoritative for the trial budget.
    # A command-line override is permitted for validation tests.
    with Path(args.config).open("rb") as stream:
        summa_config = tomllib.load(stream)

    if args.n_trials is None:
        args.n_trials = int(
            summa_config["calibration"]["n_samples"]
        )

    print("DDS trial budget:", args.n_trials, flush=True)

    if args.run_index < 1:
        parser.error("--run-index must be positive")

    if args.n_trials < 2:
        parser.error("--n-trials must be at least 2")

    if not 0 < args.perturbation_scale <= 1:
        parser.error("--perturbation-scale must be in (0,1]")

    if args.max_attempts < 1:
        parser.error("--max-attempts must be positive")

    worker = SummaWorker(args.library)

    try:
        worker.initialise(args.config)

        print("SUMMA INITIALIZED", flush=True)
        print(
            "Native calibration parameters:",
            len(worker.parameters),
            flush=True,
        )

        run_dds(worker, args)

    finally:
        worker.finalize()


if __name__ == "__main__":
    main()
