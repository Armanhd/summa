# SUMMA Python Wrapper - Development and Implementation Notes

## 1. Purpose

This document summarizes the modifications made to the coupled SUMMA codebase to expose SUMMA objective evaluation to Python.

The implementation was developed on the `python-wrapper-v4.5` branch based on SUMMA v4.5.0-exp. It is designed so that Python optimization packages can evaluate parameter sets through `libsumma.so` while retaining the existing SUMMA-mizuRoute simulation and objective-evaluation workflow.

The architecture is:

```text
Python optimizer
      |
      v
summa_ctypes.py
      |
      | ctypes / C ABI
      v
summa_python_api.f90
      |
      v
SUMMA evaluate_objective()
      |
      v
coupled SUMMA-mizuRoute
      |
      v
objective value
```

## 2. Modified and added files

### 2.1 `build/source/CMakeLists.txt`

**Status:** Modified

The Python API source was added to the SUMMA driver source list:

```cmake
${DRIVER_DIR}/python_api/summa_python_api.f90
```

This causes the wrapper to be compiled into the SUMMA shared library.

The relevant driver sequence now includes:

```cmake
${DRIVER_DIR}/summa_simulation.f90
${DRIVER_DIR}/python_api/summa_python_api.f90
${DRIVER_DIR}/summa_spinup.f90
```

### 2.2 `build/source/driver/python_api/summa_python_api.f90`

**Status:** New file

This is the thin Fortran interface between Python and SUMMA.

It exposes C-bindable entry points including:

```text
summa_py_init
summa_py_evaluate
```

The interface uses `iso_c_binding` so the functions can be called from Python through `ctypes`.

The wrapper uses the existing SUMMA configuration and simulation infrastructure, including:

```text
read_summa_config
evaluate_objective
```

The wrapper also explicitly sets:

```fortran
config_saved%read_cli = .false.
iRunMode = iRunModeFull
```

before reading the configuration.

Setting `iRunMode = iRunModeFull` is required because the Python interface bypasses SUMMA's normal command-line initialization. Without this initialization, coupled mizuRoute evaluation can incorrectly behave as though a restricted subdomain run was requested.

### 2.3 `utils/pre-processing/create_lumped_to_hru_mapping.sh`

**Status:** Modified

The reading of the SUMMA `hruId` from the forcing NetCDF file was changed from:

```bash
ncks -H -C -s '%d\n' -v hruId
```

to:

```bash
ncks -H -C -s '%.17g\n' -v hruId
```

This change is required because some forcing files store `hruId` as a floating-point NetCDF variable even though the value represents an integer identifier.

Using `%d` on these files can return an incorrect HRU ID and consequently generate an incorrect SUMMA-to-mizuRoute remapping file.

### 2.4 `python_wrapper/summa_ctypes.py`

**Status:** New file

This module provides the optimizer-independent Python interface to SUMMA.

It:

- loads `libsumma.so` using `ctypes.CDLL`;
- defines the argument interfaces for the C-bindable Fortran routines;
- initializes SUMMA from a TOML configuration;
- sends parameter names and parameter values to SUMMA;
- returns the objective value to Python.

Optimization packages should interact with this Python layer rather than directly implementing their own Fortran interface.

### 2.5 `python_wrapper/test_single_evaluation.py`

**Status:** New file

A minimal single-evaluation test.

It is used to verify the complete interface:

```text
Python
 -> ctypes
 -> libsumma.so
 -> SUMMA
 -> mizuRoute
 -> objective calculation
 -> Python
```

This should be run before attempting parallel calibration.

### 2.6 `python_wrapper/pymoo_smoke_test.py`

**Status:** New file

Provides a small Pymoo optimization smoke test.

Its purpose is to verify that Pymoo can successfully pass candidate parameter sets to the SUMMA wrapper and receive objective values.

It is intended as a software test rather than a final calibration configuration.

### 2.7 `python_wrapper/parallel/prepare_parallel_runtime.py`

**Status:** New file

Provides preparation utilities for multiprocessing tests.

Parallel workers require independent writable runtime locations because SUMMA maintains model state and can create/update state/work files.

### 2.8 `python_wrapper/parallel/pymoo_parallel_smoke.py`

**Status:** New file

Tests concurrent SUMMA evaluations using multiple Python processes.

This established the process-level parallel design used by the production Pymoo driver.

### 2.9 `python_wrapper/pymoo/calibration_config.py`

**Status:** New file

Defines calibration settings used by the Pymoo workflow, including:

- parameter names;
- lower and upper bounds;
- parameter transformations;
- default population size;
- default number of generations;
- random seed;
- paths required by the current ARC calibration setup.

For parameters spanning orders of magnitude, transformations can be applied in optimization space. For example, `k_soil` is searched in log10 space and transformed back to its physical value before SUMMA evaluation.

### 2.10 `python_wrapper/pymoo/run_calibration.py`

**Status:** New file

This is the production Pymoo calibration driver.

It provides:

- command-line basin selection;
- configurable number of workers;
- configurable population size and generations;
- process-level parallel SUMMA evaluation;
- parameter transformation;
- worker-specific runtime directories;
- use of `$SLURM_TMPDIR` when available;
- Pymoo Genetic Algorithm optimization;
- calibration history output;
- best-parameter JSON output.

The objective returned by SUMMA is KGE. Because Pymoo minimizes objectives, the driver passes:

```python
F = -KGE
```

to Pymoo, so minimizing the Pymoo objective corresponds to maximizing KGE.

## 3. Why multiprocessing is used

SUMMA contains module/global state. A shared `libsumma.so` instance should therefore not be assumed to be thread-safe.

The Python implementation uses independent operating-system processes:

```text
Worker process 1 -> independent libsumma.so instance
Worker process 2 -> independent libsumma.so instance
...
Worker process N -> independent libsumma.so instance
```

The multiprocessing start method is `spawn`, which gives each worker a clean Python process.

Do not replace this architecture with Python threads unless SUMMA's internal state handling is redesigned and thread safety is explicitly established.

## 4. Worker runtime directories

Each worker needs private writable state/work locations.

For HPC jobs, the production driver preferentially uses:

```text
$SLURM_TMPDIR
```

to reduce shared-filesystem I/O.

If Slurm temporary storage is unavailable, the driver falls back to a runtime directory under the experiment location.

Read-only/shared model inputs can still be referenced from their normal locations.

## 5. Output strategy

Calibration should normally use:

```toml
write_timeseries = false
```

so each parameter evaluation does not generate a large time-series NetCDF output.

The Pymoo driver instead writes compact optimization products:

```text
<BASIN>_pymoo_history.csv
<BASIN>_pymoo_best.json
```

The history file stores evaluated parameter sets and objective performance. The JSON file stores the best solution and run metadata.

## 6. Difference from native SUMMA MPI calibration

SUMMA's native MPI calibration executable and the Python wrapper solve different parallelization problems.

### Native SUMMA MPI calibration

Uses MPI ranks and SUMMA's compiled calibration workflow.

### Python wrapper calibration

Uses independent Python worker processes to evaluate different parameter sets concurrently.

Conceptually:

```text
Pymoo population
       |
       +-- parameter set A -> SUMMA worker A
       +-- parameter set B -> SUMMA worker B
       +-- parameter set C -> SUMMA worker C
       +-- ...
```

This is particularly useful for lumped/small-domain calibration where distributing a single simulation over many MPI ranks would provide little benefit.

## 7. Validation performed

The implementation has been tested through several stages:

1. successful compilation of `summa_python_api.f90` into `libsumma.so`;
2. verification that `summa_py_init` and `summa_py_evaluate` are exported by the shared library;
3. successful single Python/ctypes objective evaluation;
4. successful Pymoo smoke optimization;
5. successful multiprocessing Pymoo evaluation with independent workers;
6. successful production-driver smoke test using coupled SUMMA-mizuRoute.

These tests establish that the software workflow operates end-to-end. Small smoke-test optimization results are not intended to represent final basin calibration.

## 8. Current limitations and future work

Current considerations include:

- use processes rather than threads;
- the model currently appears to perform substantial SUMMA initialization during each objective evaluation, so the implementation should not be described as eliminating all per-evaluation initialization or forcing I/O;
- no explicit Python-facing finalization routine is currently exposed;
- parameter dependencies that require ordered constraints should be implemented explicitly before adding those parameters to automated optimization;
- additional optimizers can be connected to `summa_ctypes.py` without changing the core Fortran interface.

A planned extension is to connect SPOTPY/DDS to the same wrapper architecture.

## 9. Future development roadmap

The current Python wrapper establishes a working optimizer-independent interface between Python and coupled SUMMA-mizuRoute. The next development steps should focus on adding alternative optimization engines and scaling the evaluation layer without changing the core Fortran API.

### 9.1 Add SPOTPY and DDS

The first planned extension is to connect SPOTPY to the existing `summa_ctypes.py` interface and implement a DDS-based calibration workflow.

The intended architecture is:

```text
SPOTPY / DDS
     |
     v
summa_ctypes.py
     |
     v
libsumma.so
     |
     v
SUMMA + mizuRoute
     |
     v
objective value
```

The SUMMA wrapper should remain unchanged. The SPOTPY/DDS layer should only be responsible for:

- defining the parameter space;
- generating candidate parameter sets;
- applying parameter transformations;
- calling the existing SUMMA evaluation function;
- returning the objective value to SPOTPY;
- writing compact calibration results.

This provides a second optimizer frontend that can be compared directly with Pymoo while using the same hydrologic model backend.

### 9.2 Add Ray as an optional parallel execution backend

The current implementation uses Python `multiprocessing` on a single compute node. This is appropriate for initial HPC use and avoids additional dependencies.

A future extension is to support Ray as an optional execution backend.

Ray could provide:

- worker management across multiple nodes;
- dynamic scheduling of parameter evaluations;
- easier scaling beyond the CPU count of a single node;
- persistent worker actors that each own an initialized Python/SUMMA process;
- recovery and rescheduling if individual workers fail;
- a common parallel backend that can potentially be used by multiple optimizers.

The intended design is:

```text
Pymoo / SPOTPY / other optimizer
              |
              v
        evaluation backend
          /          \
 multiprocessing     Ray
   single node     multi-node
          \          /
              v
        SUMMA workers
              |
              v
         libsumma.so
```

Ray should be treated as an optional layer rather than a requirement so that the wrapper remains lightweight and usable on systems where Ray is not installed.

Before adopting Ray for production, benchmark it against the existing multiprocessing implementation. The comparison should include:

- total wall-clock time;
- worker startup overhead;
- shared-filesystem I/O;
- memory use;
- scaling from one to multiple nodes;
- scheduler overhead for short versus long SUMMA evaluations.

### 9.3 Investigate hybrid parameter-level and SUMMA domain-level parallelism

The current Python implementation parallelizes **across parameter sets**:

```text
parameter set 1 -> one SUMMA worker
parameter set 2 -> one SUMMA worker
parameter set 3 -> one SUMMA worker
...
```

SUMMA also has MPI-based domain parallelism that can distribute a single spatial simulation across GRUs/HRUs.

For sufficiently large distributed basins, a future target is a two-level or hybrid parallel configuration:

```text
Outer level: parameter-set parallelism
(Pymoo / SPOTPY / Ray)
            |
            +-- parameter set A
            |       |
            |       +-- SUMMA MPI rank 0
            |       +-- SUMMA MPI rank 1
            |       +-- SUMMA MPI rank 2
            |       +-- ...
            |
            +-- parameter set B
            |       |
            |       +-- SUMMA MPI rank 0
            |       +-- SUMMA MPI rank 1
            |       +-- ...
            |
            +-- parameter set C
                    |
                    +-- SUMMA MPI ranks ...
```

This would combine:

1. **outer parallelism** across independent calibration trials; and
2. **inner parallelism** within each model simulation across the spatial domain.

This architecture is likely unnecessary for lumped or small-domain models, where one CPU per parameter evaluation is more efficient. It becomes potentially useful when individual distributed SUMMA simulations are themselves computationally expensive.

### 9.4 Coupled mizuRoute and MPI considerations

Hybrid SUMMA MPI + Python/Ray parallelism should not be enabled automatically.

The current SUMMA documentation notes that coupled mizuRoute routing is serial and is not currently combined with the standard SUMMA MPI run path. Therefore, the exact behavior of a hybrid configuration must be established before production use.

The following cases should be investigated separately:

```text
A. Outer parameter parallelism
   + serial SUMMA
   + serial mizuRoute

B. Outer parameter parallelism
   + MPI SUMMA domain decomposition
   + serial mizuRoute

C. Outer parameter parallelism
   + MPI SUMMA
   + parallel/distributed mizuRoute, if supported in a future implementation
```

Case A is the configuration currently demonstrated by the Python wrapper.

Case B is a possible future target, but it requires a clear coupling strategy between the distributed SUMMA domain and the routing calculation. It must be verified that each trial owns an independent MPI communicator and that all runoff required by the complete river network is available to mizuRoute.

Case C would require explicit mizuRoute parallel support and should be treated as a separate development task rather than assumed to work because SUMMA itself supports MPI.

### 9.5 Avoid nested oversubscription

Any hybrid implementation must explicitly manage CPU ownership.

For example, on a 64-CPU allocation:

```text
8 parameter workers
x
8 MPI ranks per SUMMA simulation
=
64 CPUs
```

should not accidentally become:

```text
64 outer workers
x
8 inner MPI ranks
```

or allow BLAS/OpenMP threads to multiply the requested CPU count.

A future scheduler/backend should therefore make the following explicit:

- number of concurrent parameter evaluations;
- MPI ranks allocated to each evaluation;
- OpenMP/BLAS threads per rank;
- memory per evaluation;
- node placement;
- temporary working directory per evaluation.

### 9.6 Reduce repeated initialization and input I/O

The current wrapper avoids spawning a new SUMMA executable for every parameter evaluation, but testing indicates that substantial model initialization still occurs inside the objective-evaluation pathway.

A further performance-development task is to determine which model components can safely remain initialized between evaluations.

Potential targets include:

- forcing metadata and time indexing;
- static basin attributes;
- mizuRoute topology;
- observation data;
- parameter metadata;
- reusable restart/spin-up state.

The goal would be:

```text
initialize static model data once
        |
        +-- evaluate parameter set 1
        +-- reset mutable model state
        +-- evaluate parameter set 2
        +-- reset mutable model state
        +-- ...
```

This should only be implemented after confirming that state reset is complete and that repeated evaluations remain numerically identical to independent simulations.

### 9.7 Generalize optimizer configuration

The current Pymoo parameter definitions are stored in Python configuration.

A future improvement is to move optimizer-independent parameter metadata into a reusable configuration format, for example TOML or YAML, containing:

- parameter name;
- lower bound;
- upper bound;
- transformation;
- dependency/constraint information;
- whether the parameter belongs to SUMMA, mizuRoute, or another coupled component.

Both Pymoo and SPOTPY could then consume the same parameter definition.

### 9.8 Benchmark scaling before large production use

Before scaling to large calibration campaigns, perform controlled benchmarks with the same number of total model evaluations.

Suggested comparisons include:

```text
1 worker
2 workers
4 workers
8 workers
16 workers
32 workers
```

and, later:

```text
multiprocessing vs Ray
single-node vs multi-node
outer-only parallelism vs hybrid outer + SUMMA MPI
```

Record:

- wall-clock time;
- evaluations per hour;
- parallel efficiency;
- peak memory;
- shared-filesystem read/write rates;
- CPU utilization.

These benchmarks should determine the preferred parallel strategy for different basin sizes rather than assuming that more workers or nested MPI always produces faster calibration.

### 9.9 Longer-term architecture

The longer-term target is an optimizer-agnostic and execution-backend-agnostic framework:

```text
               Optimization layer
        +----------+----------+
        |                     |
      Pymoo                SPOTPY/DDS
        |                     |
        +----------+----------+
                   |
             common SUMMA
             evaluation API
                   |
        +----------+----------+
        |                     |
 multiprocessing             Ray
 single node              multi-node
        |                     |
        +----------+----------+
                   |
              libsumma.so
                   |
          SUMMA + mizuRoute
                   |
        optional inner SUMMA MPI
        for large spatial domains
```

The key design principle is to keep these layers independent. Adding a new optimizer or execution backend should not require modifying the core SUMMA Python API unless additional model capabilities are actually needed.

