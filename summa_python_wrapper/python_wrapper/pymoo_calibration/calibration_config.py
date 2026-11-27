#!/usr/bin/env python3
"""
Shared configuration reader for SUMMA Python optimization.

Scientific settings are read from SUMMA TOML files.

SUMMA's native Fortran API remains authoritative for:
  - Parameter names, bounds and transformations
  - Spatial multipliers and parameter ratios
  - Physical feasibility constraints
  - Model simulation and objective calculations

This module does not modify the SUMMA configuration.

Supported optimizer integrations:
  - Custom DDS
  - SPOTPY DDS / SCE-UA
  - pymoo GA / NSGA-II
  - SciPy Differential Evolution
  - CMA-ES

Optimizer-specific settings are handled by the optimizer.
"""

from pathlib import Path
import tomllib


SUPPORTED_ALGORITHMS = (
    "custom_dds",
    "spotpy_dds",
    "ga",
    "nsga2",
    "differential_evolution",
    "cma_es",
    "sceua",
)


def load_calibration_config(config_path):
    """
    Load and validate essential calibration settings.

    Does not change parameter definitions or objective weights.
    """

    config_path = Path(config_path).resolve()

    if not config_path.is_file():
        raise FileNotFoundError(config_path)

    with config_path.open("rb") as stream:
        config = tomllib.load(stream)

    calibration = config.get("calibration")

    if not isinstance(calibration, dict):
        raise ValueError("Missing [calibration] section")

    n_samples = int(calibration["n_samples"])

    if n_samples < 1:
        raise ValueError("n_samples must be positive")

    targets = calibration.get("target", [])

    if targets and not isinstance(targets, list):
        raise ValueError(
            "Expected [[calibration.target]] entries"
        )

    # Support the earlier single-objective TOML format.
    if not targets:
        metric = calibration.get("metric")
        if metric is None:
            raise ValueError(
                "No calibration objective defined"
            )

        targets = [{
            "name": "streamflow_" + str(metric),
            "variable": "streamflow",
            "metric": metric,
            "obs_transform": calibration.get(
                "obs_transform", "none"
            ),
            "weight": 1.0,
        }]

    targets = [dict(target) for target in targets]

    for target in targets:
        if "name" not in target or "metric" not in target:
            raise ValueError(
                "Each target needs a name and metric"
            )

        target["weight"] = float(
            target.get("weight", 1.0)
        )

        if target["weight"] < 0:
            raise ValueError(
                "Negative target weights are not supported"
            )

    active_targets = [
        target for target in targets
        if target["weight"] > 0
    ]

    if not active_targets:
        raise ValueError(
            "No positive-weight optimization target"
        )

    return {
        "config_path": config_path,
        "case_name": config["simulation"]["case_name"],
        "n_samples": n_samples,
        "start_date": calibration.get("start_date"),
        "end_date": calibration.get("end_date"),
        "targets": targets,
        "active_targets": active_targets,
        "raw_config": config,
    }


def load_manifest(manifest_path):
    """Read multi-basin configuration without modifying it."""

    manifest_path = Path(manifest_path).resolve()

    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)

    with manifest_path.open("rb") as stream:
        manifest = tomllib.load(stream)

    settings = manifest["multi_case"]

    cases = list(settings["case_names"])
    n_runs = int(settings["n_runs"])
    cases_per_node = int(settings["cases_per_node"])

    if n_runs < 1 or cases_per_node < 1:
        raise ValueError("Invalid manifest run settings")

    if not cases or len(cases) != len(set(cases)):
        raise ValueError(
            "Empty or duplicate case names in manifest"
        )

    return {
        "manifest_path": manifest_path,
        "experiment": settings["experiment"],
        "template_file": settings["template_file"],
        "case_names": cases,
        "n_cases": len(cases),
        "n_runs": n_runs,
        "cases_per_node": cases_per_node,
        "total_runs": len(cases) * n_runs,
    }
