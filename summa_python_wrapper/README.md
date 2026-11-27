# SUMMA Python Wrapper

A lightweight Python optimization interface for [SUMMA](https://github.com/CH-Earth/summa), including coupled SUMMA–mizuRoute calibration.

**SUMMA is the main hydrological modelling code.** This wrapper is an optional extension that connects Python optimizers to SUMMA through `libsumma.so`. It uses SUMMA's native TOML configuration, parameter definitions, physical constraints, model simulations and objective calculations without changing their scientific implementation. Python manages the optimization search.

The wrapper currently supports custom DDS, SPOTPY DDS, genetic algorithms (pymoo), differential evolution (SciPy), CMA-ES and SCE-UA.

## Documentation

- [User guide](USER_GUIDE.md) — installation, configuration and calibration examples
- [Development notes](DEVELOPMENT.md) — interface design, source files and integration details

## Development status

This code is being developed and tested separately before a proposed contribution to the [CH-Earth SUMMA repository](https://github.com/CH-Earth/summa), potentially through a feature branch and pull request to `develop`. **It is not yet part of the official SUMMA repository.**
