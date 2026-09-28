# SUMMA Python Wrapper and Pymoo Calibration - User Guide

## 1. Purpose

This guide explains how to use the Python wrapper to calibrate coupled SUMMA-mizuRoute simulations with a Python optimization package.

The current production implementation uses Pymoo and process-level multiprocessing.

The expected workflow is:

```text
Prepare SUMMA + mizuRoute basin
        |
        v
Prepare TOML calibration configuration
        |
        v
Test normal coupled simulation
        |
        v
Test one Python objective evaluation
        |
        v
Test small Pymoo optimization
        |
        v
Run parallel Pymoo calibration with Slurm
        |
        v
Review history CSV and best-parameter JSON
```

Do not begin a large optimization until the basin runs correctly as a normal coupled SUMMA-mizuRoute simulation.

## 2. Repository

The wrapper is maintained on:

```text
branch: python-wrapper-v4.5
```

The main source locations are:

```text
build/source/driver/python_api/summa_python_api.f90
python_wrapper/summa_ctypes.py
python_wrapper/pymoo/calibration_config.py
python_wrapper/pymoo/run_calibration.py
```

## 3. Required software

The workflow requires:

- SUMMA built as a shared library;
- mizuRoute coupling enabled;
- NetCDF C and Fortran;
- SUNDIALS if required by the selected SUMMA numerical configuration;
- Python 3;
- NumPy;
- SciPy;
- Pymoo.

On an HPC system, use the same compiler and linked-library environment used to build `libsumma.so`.

## 4. Load the model environment

On the University of Calgary ARC implementation used during development:

```bash
source /work/comphyd_lab/users/arman.haddadchi/hydro_models/load_model_env.sh
```

The optimization Python environment is:

```text
/home/arman.haddadchi/.conda/envs/summa_opt
```

A convenience environment loader is:

```bash
source /work/comphyd_lab/users/arman.haddadchi/hydro_models/load_summa_opt_env.sh
```

This sets:

```bash
SUMMA_OPT_PYTHON=/home/arman.haddadchi/.conda/envs/summa_opt/bin/python
```

Verify:

```bash
"$SUMMA_OPT_PYTHON" --version
```

For another computer or HPC system, replace these ARC-specific paths with the local SUMMA and Python environment locations.

## 5. Build the coupled SUMMA shared library

The Python API must be compiled into `libsumma.so`.

The source tree contains:

```text
build/source/driver/python_api/summa_python_api.f90
```

and `build/source/CMakeLists.txt` includes this file in the driver sources.

Configure SUMMA with the features required by the basin. For coupled SUMMA-mizuRoute with SUNDIALS, the relevant options include:

```text
USE_SUNDIALS=ON
USE_MIZUROUTE=ON
USE_MPI=OFF
USE_NEXTGEN=OFF
USE_OPENWQ=OFF
```

Use a separate build directory.

Example ARC layout:

```bash
SUMMA_ROOT=/work/comphyd_lab/users/arman.haddadchi/hydro_models/summa_v4.5_python
SUMMA_SRC="$SUMMA_ROOT/build"
BUILD=/work/comphyd_lab/users/arman.haddadchi/hydro_models/builds/summa_v4.5_python_coupled
```

If an existing build was configured before the Python API was added, clear the cached `DRIVER` variable when reconfiguring:

```bash
cmake -U DRIVER \
  -S "$SUMMA_SRC" \
  -B "$BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DUSE_SUNDIALS=ON \
  -DSUNDIALS_DIR="$SUNDIALS_DIR" \
  -DUSE_MIZUROUTE=ON \
  -DUSE_MPI=OFF \
  -DUSE_NEXTGEN=OFF \
  -DUSE_OPENWQ=OFF
```

Then build:

```bash
cmake --build "$BUILD" -j 8
```

## 6. Verify the Python API is present

Find the generated shared library and check the exported functions:

```bash
nm -D /path/to/libsumma.so | grep summa_py
```

Expected symbols include:

```text
summa_py_init
summa_py_evaluate
```

If these are absent, confirm that `summa_python_api.f90` was included in the CMake driver sources and rebuild.

## 7. Prepare a new basin

Before using Python, prepare the basin exactly as required for a normal coupled SUMMA-mizuRoute simulation.

The basin needs, at minimum:

- SUMMA forcing;
- SUMMA attributes/parameters;
- SUMMA file manager/settings;
- initial/cold-state file;
- mizuRoute river topology;
- SUMMA-to-mizuRoute remapping;
- mizuRoute settings;
- streamflow observations for calibration;
- a TOML configuration describing the simulation and objective evaluation.

Run the basin normally first.

The Python wrapper is not a replacement for basin preprocessing or for validating the physical SUMMA-mizuRoute configuration.

## 8. Check HRU IDs and remapping

For lumped SUMMA, verify that the forcing HRU ID, SUMMA HRU ID, and remapping HRU ID agree.

The remapping helper is:

```text
utils/pre-processing/create_lumped_to_hru_mapping.sh
```

The current branch reads floating-point NetCDF `hruId` values using:

```bash
ncks -H -C -s '%.17g\n' -v hruId
```

This prevents incorrect IDs when `hruId` is stored as a floating-point variable.

After creating the remapping file, inspect it and confirm that the SUMMA HRU maps to the intended mizuRoute reach.

## 9. Prepare the TOML configuration

The Python wrapper initializes SUMMA using the same TOML-based configuration infrastructure used by the coupled calibration workflow.

For each basin, prepare a valid configuration containing the required sections for:

- simulation period;
- SUMMA input/settings;
- mizuRoute coupling;
- observations;
- calibration/evaluation period;
- objective metric;
- parameter information as required by the underlying configuration.

For calibration runs, normally use:

```toml
write_timeseries = false
```

This is important for reducing I/O during hundreds or thousands of parameter evaluations.

Use daily observations if the objective is intended to be evaluated at daily resolution, even if the physical SUMMA-mizuRoute simulation operates hourly.

## 10. Validate the normal coupled simulation

Before testing Python, run the coupled model using the normal SUMMA executable.

Confirm:

- simulation starts and finishes;
- SUMMA runoff is nonzero and plausible;
- mizuRoute receives runoff;
- outlet reach is correct;
- routed discharge is produced;
- simulation dates are correct;
- observations overlap the calibration period.

Do not debug Python and basin configuration simultaneously.

## 11. Test one Python evaluation

The repository includes:

```text
python_wrapper/test_single_evaluation.py
```

Run a single evaluation before using an optimizer.

Conceptually, this tests:

```text
Python
 -> summa_ctypes.py
 -> libsumma.so
 -> summa_py_init
 -> summa_py_evaluate
 -> coupled SUMMA-mizuRoute
 -> KGE
 -> Python
```

A successful test should return a numerical objective value without launching a separate SUMMA executable.

## 12. Configure calibration parameters

Pymoo settings are currently defined in:

```text
python_wrapper/pymoo/calibration_config.py
```

For each parameter define:

- name;
- lower bound;
- upper bound;
- transformation, if required.

Example concept:

```python
{
    "name": "k_soil",
    "lower": 1.0e-7,
    "upper": 1.0e-5,
    "transform": "log10",
}
```

Parameters spanning several orders of magnitude should generally be considered for logarithmic search rather than uniform linear search.

The current implementation transforms optimization-space values back to physical SUMMA values before calling the model.

## 13. Parameter dependencies

Do not independently optimize parameters that have structural ordering constraints unless the optimizer explicitly enforces those constraints.

For example, canopy-top and canopy-bottom heights require an ordered relationship. These parameters were intentionally excluded from the initial production Pymoo parameter list until the dependency is handled explicitly.

The same principle applies to any parameter group whose physically valid range depends on another parameter.

## 14. Run a small Pymoo smoke test

Before a production calibration, use a very small population and generation count.

For example:

```bash
"$SUMMA_OPT_PYTHON" \
  python_wrapper/pymoo/run_calibration.py \
  --basin CAN_01AD003 \
  --workers 4 \
  --population 4 \
  --generations 2 \
  --seed 1
```

This is only a software validation run.

Check that:

- workers start;
- SUMMA evaluations finish;
- Pymoo reports generations/evaluations;
- KGE values are returned;
- the history CSV is created;
- the best JSON is created.

Do not interpret an 8-evaluation smoke test as a calibrated model.

## 15. Understand the objective sign

SUMMA returns KGE as the model performance metric.

Higher KGE is better, but Pymoo minimizes objective functions.

Therefore the driver uses:

```python
F = -KGE
```

Pymoo minimizes `-KGE`, which is equivalent to maximizing KGE.

The output JSON/history should report KGE in its normal interpretation.

## 16. Parallel worker design

Each worker is a separate Python process.

For example:

```text
Pymoo
 |
 +-- worker 1 -> libsumma.so -> trial 1
 +-- worker 2 -> libsumma.so -> trial 2
 +-- worker 3 -> libsumma.so -> trial 3
 +-- worker 4 -> libsumma.so -> trial 4
```

Do not use Python threads for SUMMA evaluations.

The multiprocessing implementation uses `spawn` so each worker starts with an independent process and library state.

## 17. Worker-specific runtime directories

Workers must not simultaneously write to the same state/work directory.

The production driver creates private runtime directories for each worker.

On Slurm, it preferentially uses:

```bash
$SLURM_TMPDIR
```

which reduces shared-filesystem I/O.

If local Slurm temporary storage is unavailable, it falls back to the configured experiment runtime directory.

Shared read-only inputs can still be referenced through their normal paths.

## 18. Avoid CPU oversubscription

When running many SUMMA worker processes, prevent numerical libraries from creating additional threads inside each worker.

In the Slurm script set:

```bash
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
```

If requesting 40 CPUs and using 40 Python workers, this keeps the intended layout close to one CPU per SUMMA worker.

## 19. Production Slurm job

For a larger calibration, submit the Python driver through Slurm rather than running on the login node.

A representative configuration is:

```bash
#!/bin/bash
#SBATCH --job-name=summa_pymoo
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=40
#SBATCH --mem=80G
#SBATCH --time=12:00:00

source /work/comphyd_lab/users/arman.haddadchi/hydro_models/load_summa_opt_env.sh

export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1

"$SUMMA_OPT_PYTHON" \
  /path/to/summa/python_wrapper/pymoo/run_calibration.py \
  --basin CAN_01AD003 \
  --workers 40 \
  --population 40 \
  --generations 20 \
  --seed 1
```

With population 40 and 20 generations, approximately 800 parameter evaluations are expected.

Adjust memory, wall time, population size, generations, and worker count for the basin and HPC system.

## 20. Output files

The production Pymoo driver writes two main outputs for each basin:

```text
<BASIN>_pymoo_history.csv
<BASIN>_pymoo_best.json
```

### History CSV

Contains the optimization history, including:

- generation;
- individual;
- KGE;
- evaluated parameter values.

Use this file to examine convergence, parameter exploration, and the progression of model performance.

### Best JSON

Contains summary metadata and the best solution, including:

- basin;
- optimizer;
- metric;
- number of workers;
- population;
- generations;
- approximate evaluations;
- random seed;
- elapsed time;
- best KGE;
- best parameter values.

## 21. Recommended workflow for every new basin

Use this sequence:

```text
1. Prepare basin SUMMA inputs.
2. Prepare mizuRoute topology and settings.
3. Generate/check SUMMA-to-mizuRoute remapping.
4. Prepare observations.
5. Prepare TOML configuration.
6. Run normal coupled SUMMA-mizuRoute.
7. Verify outlet discharge and observation overlap.
8. Run one Python wrapper evaluation.
9. Run a tiny Pymoo smoke test.
10. Run a small parallel smoke test.
11. Submit production Pymoo calibration with Slurm.
12. Inspect convergence and best parameters.
13. Run the selected best parameter set as a normal model simulation.
14. Generate final time-series outputs only for selected/final runs.
```

This sequence isolates problems and avoids wasting HPC resources on configuration errors.

## 22. Adding another optimizer

The Python/Fortran interface is intentionally independent of Pymoo.

A new optimizer should reuse:

```text
python_wrapper/summa_ctypes.py
```

The optimizer only needs to:

1. generate a parameter vector;
2. convert optimizer-space values to physical values where necessary;
3. call the SUMMA wrapper;
4. receive the objective value;
5. return that value in the convention required by the optimizer.

SPOTPY/DDS can therefore be added as another frontend without redesigning the Fortran API.

## 23. Troubleshooting

### `summa_py_init` or `summa_py_evaluate` is missing

Check:

```bash
nm -D /path/to/libsumma.so | grep summa_py
```

If the symbols are absent, rebuild after confirming that:

```text
build/source/driver/python_api/summa_python_api.f90
```

is included in `build/source/CMakeLists.txt`.

### Incorrect HRU mapping

Inspect the forcing `hruId` type/value and regenerate the mapping with the updated helper script.

### mizuRoute reports a subdomain/run-mode error

Confirm that the Python API contains:

```fortran
iRunMode = iRunModeFull
```

before configuration initialization.

### Serial wrapper works but multiprocessing fails

Check that:

- multiprocessing uses processes, not threads;
- workers use `spawn`;
- each worker has its own writable state/work directory;
- workers do not overwrite the same files.

### Calibration creates excessive files

Set:

```toml
write_timeseries = false
```

for optimization trials.

Only generate full time-series outputs after selecting final parameter sets.

### CPU use is much larger than requested

Set:

```bash
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
```

before launching the Python calibration.

### Optimization runs but performance does not improve

Check:

- objective sign;
- parameter bounds;
- parameter transformations;
- calibration period;
- observation units;
- temporal aggregation;
- outlet reach;
- parameter dependencies;
- whether enough evaluations/generations were used.

## 24. Important implementation note

The Python wrapper avoids launching a separate SUMMA executable for every parameter evaluation.

However, current testing indicates that substantial model initialization still occurs during individual calls to the objective-evaluation pathway. Therefore, do not assume that forcing, topology, and all model state remain permanently initialized in memory between trials.

Further optimization of repeated-evaluation initialization and I/O can be considered separately without changing the external optimizer interface.
