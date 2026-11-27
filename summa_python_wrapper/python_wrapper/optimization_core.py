#!/usr/bin/env python3
"""
Shared SUMMA optimization evaluation layer.

Provides:
- Native parameter feasibility checking
- SUMMA model evaluation
- Single- and multiobjective fitness conversion
- Native NetCDF trial recording
- Evaluation and simulation counters
- Best-solution tracking

No optimizer-specific or basin-specific settings.
"""

from datetime import datetime
import math

import numpy as np


FAILURE_PENALTY = 1.0e6

# SUMMA efficiency metrics: larger is better.
EFFICIENCY_METRICS = {"kge", "nse"}


def objective_losses(objectives, targets):
    """
    Convert native SUMMA objectives to minimization losses.

    Returns one loss for each positive-weight target.
    Zero-weight diagnostics are excluded from optimization,
    but remain in the native output.
    """
    if len(objectives) != len(targets):
        raise ValueError("Objective/target count mismatch")

    losses = []

    for value, target in zip(objectives, targets):
        weight = float(target.get("weight", 1.0))

        if weight <= 0:
            continue

        metric = str(target["metric"]).lower()

        if metric not in EFFICIENCY_METRICS:
            raise ValueError(
                f"Unsupported objective metric: {metric}"
            )

        value = float(value)

        if not math.isfinite(value):
            raise ValueError("Non-finite active objective")

        losses.append(1.0 - value)

    if not losses:
        raise ValueError("No positive-weight objectives")

    return np.asarray(losses, dtype=float)


def weighted_score(objectives, targets):
    """Weighted mean loss for single-objective optimizers."""
    losses = objective_losses(objectives, targets)

    weights = np.asarray(
        [
            float(target.get("weight", 1.0))
            for target in targets
            if float(target.get("weight", 1.0)) > 0
        ],
        dtype=float,
    )

    return float(np.average(losses, weights=weights))


class SummaEvaluator:
    """Evaluate candidates using one initialized SUMMA worker."""

    def __init__(self, model, space, targets, budget):
        self.model = model
        self.space = space
        self.targets = list(targets)
        self.budget = int(budget)

        if self.budget < 1:
            raise ValueError("budget must be positive")

        self.n_active = sum(
            float(t.get("weight", 1.0)) > 0
            for t in self.targets
        )

        if self.n_active == 0:
            raise ValueError("No active optimization targets")

        self.trial_count = 0
        self.simulation_count = 0
        self.failed_count = 0

        self.best_score = float("inf")
        self.best_trial = None
        self.best_physical = None

    def evaluate_search(self, search_values):
        """
        Evaluate one candidate in transformed search coordinates.

        Returns scalar and vector minimization objectives.
        Uses the native output writer for each attempted candidate.
        """
        if self.trial_count >= self.budget:
            raise RuntimeError("Evaluation budget exceeded")

        trial = self.trial_count + 1
        physical = self.space.search_to_physical(search_values)

        start = datetime.now().astimezone()

        objectives = [float("nan")] * len(self.targets)
        failed = True

        feasible = self.model.feasible(physical)

        if not isinstance(feasible, (bool, np.bool_)):
            raise TypeError(
                "Expected Boolean native feasibility result"
            )

        if feasible:
            self.simulation_count += 1

            result = self.model.evaluate(physical)
            values = result.get("objectives", [])

            if (
                result.get("success", False)
                and not result.get("trial_failed", True)
                and len(values) == len(self.targets)
            ):
                objectives = [float(v) for v in values]
                failed = False

        if not failed:
            try:
                scalar = weighted_score(
                    objectives, self.targets
                )
                vector = objective_losses(
                    objectives, self.targets
                )
            except ValueError:
                failed = True

        if failed:
            scalar = FAILURE_PENALTY
            vector = np.full(
                self.n_active, FAILURE_PENALTY
            )
            self.failed_count += 1

        end = datetime.now().astimezone()

        self.model.output_write(
            trial=trial,
            values=physical,
            objectives=objectives,
            failed=failed,
            start_time=start,
            end_time=end,
        )

        self.trial_count = trial

        if not failed and scalar < self.best_score:
            self.best_score = scalar
            self.best_trial = trial
            self.best_physical = np.asarray(
                physical, dtype=float
            ).copy()

        return {
            "trial": trial,
            "scalar": float(scalar),
            "vector": vector,
            "objectives": objectives,
            "failed": failed,
            "feasible": bool(feasible),
        }
