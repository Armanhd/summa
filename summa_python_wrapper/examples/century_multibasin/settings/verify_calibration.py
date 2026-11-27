#!/usr/bin/env python3
"""Verify native SUMMA calibration outputs before marking a run complete.

Checks trial numbering, failure flags, algorithm metadata, and best
physical parameters. Supports legitimate early stopping.
Read-only: does not modify NetCDF files or submit jobs.
"""

import argparse
import re
import subprocess
from pathlib import Path


def ncdump(path, *args):
    return subprocess.check_output(
        ["ncdump", *args, str(path)], text=True, stderr=subprocess.PIPE
    )


def values(text, name):
    text = text.split("data:", 1)[-1]
    match = re.search(rf"\b{name}\s*=\s*([^;]+);", text)
    if not match:
        raise ValueError(f"Missing variable data: {name}")
    return [v.strip() for v in match.group(1).split(",")]


def verify(folder, algorithm, budget):
    files = list(folder.glob("*_calibration.nc"))
    if len(files) != 1:
        raise ValueError("Expected exactly one calibration NetCDF")

    cal = files[0]
    header = ncdump(cal, "-h")
    data = ncdump(cal, "-v", "sample,trial_failed")

    match = re.search(r"\bsample\s*=\s*(\d+)\s*;", header)
    if not match or int(match.group(1)) != budget:
        raise ValueError("Incorrect allocated trial count")

    native_names = {"de": "differential_evolution", "cmaes": "cma_es"}
    expected = native_names.get(algorithm, algorithm)
    if f':algorithm = "{expected}"' not in header:
        raise ValueError("Algorithm metadata mismatch")

    samples = values(data, "sample")
    flags = values(data, "trial_failed")

    if len(samples) != budget or len(flags) != budget:
        raise ValueError("Incorrect NetCDF record lengths")

    completed = sum(v != "_" for v in samples)
    if not 1 <= completed <= budget:
        raise ValueError("No completed trial records")

    if samples != [str(i) for i in range(1, completed + 1)] + \
                  ["_"] * (budget - completed):
        raise ValueError("Invalid trial numbering or unused records")

    if any(v not in ("0", "1") for v in flags[:completed]):
        raise ValueError("Invalid failure indicators")
    if any(v != "_" for v in flags[completed:]):
        raise ValueError("Unused trials contain failure indicators")

    successes = flags[:completed].count("0")
    failures = flags[:completed].count("1")
    best_files = list(folder.glob("*_sample*_trialParams.nc"))

    if successes == 0 or len(best_files) != 1:
        raise ValueError("Missing successful trial or best parameters")

    best_header = ncdump(best_files[0], "-h")
    match = re.search(r":calibration_sample\s*=\s*(\d+)\s*;", best_header)
    if not match:
        raise ValueError("Missing best-trial metadata")

    best_trial = int(match.group(1))
    if not 1 <= best_trial <= completed or flags[best_trial - 1] != "0":
        raise ValueError("Best trial is not successful")

    print(
        f"PASS {algorithm:12} recorded={completed}/{budget} "
        f"success={successes} failed={failures} "
        f"unused={budget-completed} best={best_trial}"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder", required=True, type=Path)
    parser.add_argument("--algorithm", required=True)
    parser.add_argument("--budget", required=True, type=int)
    args = parser.parse_args()

    try:
        verify(args.folder, args.algorithm, args.budget)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"FAIL: {exc}\n")


if __name__ == "__main__":
    main()
