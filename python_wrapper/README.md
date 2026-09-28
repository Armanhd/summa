# SUMMA Python Wrapper

This directory documents the Python interface added to the `python-wrapper-v4.5` branch of SUMMA.

The wrapper allows external Python optimization and calibration frameworks to evaluate coupled SUMMA-mizuRoute simulations directly through the SUMMA shared library (`libsumma.so`). The current implementation includes a Pymoo-based calibration workflow with process-level parallel evaluation of independent parameter sets.

## Purpose

The Python wrapper provides a lightweight connection between Python optimization tools and the existing SUMMA calibration/evaluation routines.

The current workflow is:

```text
Python optimizer (e.g., Pymoo)
        |
        | multiprocessing
        v
python_wrapper/summa_ctypes.py
        |
        | ctypes / C ABI
        v
libsumma.so
        |
        v
SUMMA + mizuRoute
        |
        v
objective evaluation (e.g., KGE)
```

The optimizer therefore does not need to launch a separate `summa.exe` process for every parameter set. Each Python worker process loads its own SUMMA shared-library instance and evaluates parameter sets through the wrapper.

Because SUMMA uses module/global state internally, the current parallel implementation uses **processes rather than threads**.

## Current implementation

The branch currently provides:

- a C-bindable Fortran API for initializing and evaluating SUMMA;
- a Python `ctypes` interface to `libsumma.so`;
- support for coupled SUMMA-mizuRoute objective evaluation;
- process-level parallel parameter evaluation;
- a Pymoo Genetic Algorithm calibration workflow;
- worker-private state/work directories;
- compact calibration history and best-parameter outputs;
- support for transformed parameter search, including log10 search for parameters such as `k_soil`.

## Documentation

Two documents provide the detailed information:

- [Development and implementation notes](DEVELOPMENT.md) - files added or modified in SUMMA and the purpose of each change.
- [User guide](USER_GUIDE.md) - step-by-step instructions for preparing a basin, configuring the wrapper, testing it, and running parallel Pymoo calibration.

## Main source locations

```text
build/source/driver/python_api/
    summa_python_api.f90

python_wrapper/
    summa_ctypes.py
    test_single_evaluation.py
    pymoo_smoke_test.py

    parallel/
        prepare_parallel_runtime.py
        pymoo_parallel_smoke.py

    pymoo/
        calibration_config.py
        run_calibration.py
```

The Fortran wrapper is compiled into `libsumma.so` through:

```text
build/source/CMakeLists.txt
```

## Parallelization model

The Python calibration workflow uses **parameter-level parallelism**.

For example, with 40 workers, up to 40 independent parameter sets can be evaluated concurrently:

```text
Pymoo
  |
  +-- Worker 1  -> libsumma.so -> parameter set 1
  +-- Worker 2  -> libsumma.so -> parameter set 2
  +-- ...
  +-- Worker 40 -> libsumma.so -> parameter set 40
```

This is different from SUMMA MPI domain parallelism, where GRUs from a single simulation are distributed across MPI ranks.

For lumped or small-basin calibration, parameter-level multiprocessing is generally the intended mode for this wrapper.

## Status

The Python interface, coupled SUMMA-mizuRoute evaluation, multiprocessing workflow, and Pymoo calibration driver have been tested successfully on the University of Calgary ARC system.

The included small optimization runs are validation/smoke tests of the software workflow and should not be interpreted as final calibrated parameter results.

Future extensions can connect other Python optimization packages, such as SPOTPY/DDS, to the same optimizer-independent `summa_ctypes.py` layer.
