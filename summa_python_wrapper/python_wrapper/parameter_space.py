#!/usr/bin/env python3
"""
Shared parameter-space utilities for SUMMA Python optimization.

Parameter definitions and physical constraints come from SUMMA's
Fortran API. This module only converts between physical parameter
values, transformed search coordinates, and normalized [0, 1]
coordinates.

Supported transformations:
    none  - linear physical parameter
    log   - natural logarithm of physical parameter

This module is independent of any optimization algorithm.
"""

import math

import numpy as np


class ParameterSpace:
    """Represent the parameter space supplied by native SUMMA."""

    def __init__(self, parameters):
        if not parameters:
            raise ValueError("SUMMA returned no parameters")

        self.parameters = [dict(p) for p in parameters]
        self.names = [p["name"] for p in self.parameters]
        self.n_parameters = len(self.parameters)

        if len(set(self.names)) != self.n_parameters:
            raise ValueError("Duplicate SUMMA parameter names")

        self.search_lower = np.array(
            [p["search_lower"] for p in self.parameters],
            dtype=float,
        )
        self.search_upper = np.array(
            [p["search_upper"] for p in self.parameters],
            dtype=float,
        )

        self.physical_lower = np.array(
            [p["lower"] for p in self.parameters],
            dtype=float,
        )
        self.physical_upper = np.array(
            [p["upper"] for p in self.parameters],
            dtype=float,
        )

        self.transforms = [
            p["transform"] for p in self.parameters
        ]

        if not np.all(np.isfinite(self.search_lower)):
            raise ValueError("Non-finite lower search bounds")

        if not np.all(np.isfinite(self.search_upper)):
            raise ValueError("Non-finite upper search bounds")

        if np.any(self.search_lower >= self.search_upper):
            raise ValueError("Invalid search bounds")

        for i, transform in enumerate(self.transforms):
            if transform not in ("none", "log"):
                raise ValueError(
                    f"Unsupported transformation for "
                    f"{self.names[i]}: {transform}"
                )
            if transform == "log" and self.physical_lower[i] <= 0:
                raise ValueError(
                    f"Log parameter must be positive: {self.names[i]}"
                )

    def _vector(self, values):
        arr = np.asarray(values, dtype=float)

        if arr.shape != (self.n_parameters,):
            raise ValueError(
                f"Expected {self.n_parameters} parameter values, "
                f"received shape {arr.shape}"
            )

        if not np.all(np.isfinite(arr)):
            raise ValueError("Non-finite parameter values")

        return arr

    def search_to_physical(self, values):
        """Convert optimizer coordinates into physical SUMMA values."""

        x = self._vector(values)

        if np.any(x < self.search_lower - 1e-10) or \
           np.any(x > self.search_upper + 1e-10):
            raise ValueError("Search coordinates outside bounds")

        physical = x.copy()

        for i, transform in enumerate(self.transforms):
            if transform == "log":
                physical[i] = math.exp(x[i])

        return physical

    def physical_to_search(self, values):
        """Convert physical SUMMA values into optimizer coordinates."""

        physical = self._vector(values)
        search = physical.copy()

        for i, transform in enumerate(self.transforms):
            if transform == "log":
                if physical[i] <= 0:
                    raise ValueError(
                        f"Nonpositive parameter: {self.names[i]}"
                    )
                search[i] = math.log(physical[i])

        return search

    def normalized_to_physical(self, values):
        """Convert [0,1] coordinates into physical SUMMA values."""

        z = self._vector(values)

        if np.any(z < 0.0) or np.any(z > 1.0):
            raise ValueError("Normalized values must lie in [0,1]")

        search = (
            self.search_lower
            + z * (self.search_upper - self.search_lower)
        )

        return self.search_to_physical(search)

    def physical_to_normalized(self, values):
        """Convert physical SUMMA values into [0,1] coordinates."""

        search = self.physical_to_search(values)

        return (
            (search - self.search_lower)
            / (self.search_upper - self.search_lower)
        )

    def bounds(self):
        """Return transformed search bounds for SciPy and pymoo."""
        return self.search_lower.copy(), self.search_upper.copy()

    def parameter_dict(self, values):
        """Return a named dictionary of physical parameter values."""

        physical = self._vector(values)

        return dict(zip(self.names, physical.tolist()))
