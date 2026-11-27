# SUMMA Python Wrapper — User Guide

> **Status:** Documentation draft based on the FIR-tested PR675-compatible implementation (November 2026). Replace the example repository URL and verify installation on a clean checkout before treating this as a release guide.

## 1. Purpose

The SUMMA Python wrapper provides a **simple, lightweight interface** that connects Python optimization algorithms to coupled SUMMA–mizuRoute through the compiled `libsumma.so` library. **It uses SUMMA's existing simulation and calibration routines without modifying the underlying model calculations or introducing additional input/output (I/O) operations during parameter evaluations.** It also uses SUMMA's native TOML configuration files, ensuring consistency with the original model setup.

**SUMMA** handles parameter definitions, transformations, physical constraints, simulations, and objective calculations, while **Python** generates candidate parameter sets and manages the optimization process. The wrapper avoids launching a new SUMMA executable for each trial, and each independent calibration runs in a separate process.

## 2. Requirements

- A compatible **SUMMA calibration source** containing the native modules called by `fortran_api/summa_python_api.f90` (the FIR implementation is associated with commit `98b8450423b6b4558c855363772f5b3c6b315cd7`). The wrapper does **not** supply or replace SUMMA itself.
- CMake, C/Fortran compiler, MPI, NetCDF C/Fortran; SUNDIALS and mizuRoute for the tested coupled configuration.
- Python **3.11 or newer** (`tomllib` is used), plus `numpy`; algorithm-specific packages: `pymoo` (GA), `scipy` (DE), `cma` (CMA-ES), `spotpy` (SPOTPY DDS/SCE-UA). Custom DDS uses the standard library and NumPy.
- Working model input data and observations for the selected basin.

**Verified FIR software environment:** `StdEnv/2023`, `gcc/12.3`, `openmpi/4.1.5`, `netcdf/4.9.2`, `netcdf-fortran/4.6.1`, `cmake/3.31.0`, `openblas/0.3.24`, locally built SUNDIALS 7.3.0. Adapt module names to your system.

## 3. Download SUMMA and the Python wrapper

The SUMMA Python wrapper is maintained within the SUMMA source repository on the `feature/python-wrapper` branch.

This branch contains:
1. **SUMMA:** The hydrological model and its native calibration routines.
2. **SUMMA Python Wrapper:** The Python interface, optimization algorithms, Fortran API, and installation script, located in the `summa_python_wrapper/` directory.

First, create a working directory:

```bash
mkdir -p ~/summa_workspace
cd ~/summa_workspace
```

Clone the SUMMA repository with the Python wrapper:

```bash
git clone --branch feature/python-wrapper \
  https://github.com/Armanhd/summa.git summa
```

**Note:** The `feature/python-wrapper` branch contains the Python wrapper together with the SUMMA source code. It is based on the upstream SUMMA `develop` branch. The wrapper integration with this revision should be compiled and tested before production use.

Create a separate directory for compiling SUMMA:

```bash
mkdir -p build/summa_python
```

Your directory structure should now look like this:

```text
summa_workspace/
├── summa/                       # SUMMA source code
│   ├── summa_python_wrapper/    # Python wrapper source code
│   │   ├── fortran_api/
│   │   ├── python_wrapper/
│   │   └── install_wrapper.py
│   └── ...
└── build/
    └── summa_python/            # Compilation directory
```

Finally, define the paths used throughout this guide:

```bash
export SUMMA="$HOME/summa_workspace/summa"
export WRAPPER="$SUMMA/summa_python_wrapper"
export BUILD="$HOME/summa_workspace/build/summa_python"
```

These paths will be used in the following steps to install the Python interface, compile `libsumma.so`, and run calibration.

**Do not compile SUMMA yet.** The next section explains how to install the Fortran API into the SUMMA source tree before building the shared library.



## 4. Load model libraries and Python environment

For the validated FIR environment:

```bash
source /path/to/summa/load_model_env_fir.sh
# For runs on FIR, the production launcher additionally loads scipy-stack/2024b
```

On a different system, load matching compiler/MPI/NetCDF/SUNDIALS modules and install Python dependencies in a dedicated environment:

```bash
python3 -m venv /path/to/venv
source /path/to/venv/bin/activate
python -m pip install numpy scipy pymoo cma spotpy
python --version
```

Use a Python runtime and shared libraries compatible with the compiled Fortran library. The **environment loader** sets software/library paths; the **scientific TOML** below does not load software modules.

## 5. Install the Fortran API and compile `libsumma.so`

The installer copies one Fortran file and updates SUMMA's two CMake files. It is dry-run by default; it does **not** compile the model or install Python packages.

```bash
python "$WRAPPER/install_wrapper.py" --summa-source "$SUMMA"
python "$WRAPPER/install_wrapper.py" --summa-source "$SUMMA" --apply
```

For the tested coupled MPI/SUNDIALS/TOML configuration, the relevant CMake options were:

```bash
mkdir -p "$BUILD"
cmake -S "$SUMMA/build" -B "$BUILD" \
  -DCMAKE_Fortran_COMPILER="$(command -v gfortran)" \
  -DCMAKE_C_COMPILER="$(command -v gcc)" \
  -DCMAKE_CXX_COMPILER="$(command -v g++)" \
  -DCMAKE_Fortran_FLAGS='-ffree-line-length-none' \
  -DUSE_MPI=ON -DUSE_SUNDIALS=ON \
  -DUSE_MIZUROUTE=ON -DUSE_TOML=ON \
  -DSUNDIALS_DIR="$SUNDIALS_DIR" \
  -DCMAKE_PREFIX_PATH="$SUNDIALS_ROOT" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_POSITION_INDEPENDENT_CODE=ON
cmake --build "$BUILD" --target summa --parallel 8
nm -D "$BUILD/libsumma.so" | grep summa_py_
```

The tested FIR build had `BUILD_SHARED_LIBS=OFF`, yet produced `libsumma.so` as its `summa` target. Do not assume that setting `BUILD_SHARED_LIBS=ON` is required. If reusing a prior CMake build directory, confirm that the Python API source was discovered and compiled.

## 6. Prepare and validate a basin

Prepare ordinary SUMMA/mizuRoute inputs first: forcings, attributes, model decisions and parameter tables, cold-state file, mizuRoute routing/topology and HRU-to-reach mapping, streamflow observations, and a valid SUMMA calibration TOML. Check forcing/attribute HRU IDs and the routed outlet. Run and validate a normal coupled model simulation before debugging the Python optimizer.

For calibration, `write_timeseries = false` reduces repeated trial output. Do not confuse this switch with native **calibration NetCDF**, which is recorded separately.

## 7. Configure scientific calibration (SUMMA TOML)

The SUMMA TOML specifies the case, simulation and spin-up periods, file paths, mizuRoute coupling, observations, calibration targets/weights, and native parameter definitions. The current `pymoo_calibration/calibration_config.py` *reads* this file; it does **not** define parameter bounds. SUMMA supplies physical parameter names, bounds, log transforms, ratios and feasibility checks.

Important: **`state_path` must be writable for restart output**. In the tested Slurm launcher, the cold-state input is symlinked into a private node-local `summa_state` directory and the rendered TOML points there; the trial `output_path` is also redirected to scratch. Do not point multiple tasks at one writable restart directory.

## 8. Verify one Python evaluation

Use `python_wrapper/test_single_evaluation.py` as the smoke-test source. Check its local arguments/configuration before running (it is not the same CLI as the optimizer scripts). At minimum verify that:

```bash
nm -D "$BUILD/libsumma.so" | grep -E 'summa_py_(init|evaluate|get_parameter)'
```

A passing end-to-end evaluation must load the library, initialize SUMMA, obtain parameters, check feasibility, and return finite objective values from coupled SUMMA–mizuRoute.

## 9. Run one calibration

The current drivers accept `--config`, `--library`, `--output-prefix`, `--n-evaluations`, `--run-index`, `--seed` and `--dry-run`. Use a **concrete, fully resolved** model TOML (not the placeholder template). An example:

```bash
export PYWRAP="$WRAPPER/python_wrapper"
export CONFIG=/path/to/resolved_summa_config.toml
export LIB="$BUILD/libsumma.so"
mkdir -p /path/to/results

python "$PYWRAP/pymoo_calibration/run_calibration.py" \
  --config "$CONFIG" --library "$LIB" \
  --output-prefix /path/to/results/GA_test \
  --n-evaluations 20 --population-size 10 \
  --seed 42 --run-index 1 --dry-run
```

Remove `--dry-run` **only after** the one-evaluation test and writable-path checks pass. Use unique output prefixes for each run.

| Algorithm | Current entry-point | Main options in addition to common options |
|---|---|---|
| Custom DDS | `algorithms/custom_dds.py` | `--perturbation-scale`, `--boundary-method reflect\|reject`, `--max-attempts` |
| SPOTPY DDS | `algorithms/spotpy_dds.py` | `--perturbation-scale` |
| GA (pymoo) | `pymoo_calibration/run_calibration.py` | `--population-size`, `--crossover-prob`, `--crossover-eta`, `--mutation-prob`, `--mutation-eta` |
| Differential Evolution (SciPy) | `run_de_calibration.py` | `--population-size`, `--strategy`, `--mutation`, `--crossover` |
| CMA-ES | `run_cmaes_calibration.py` | `--population-size`, `--sigma` |
| SCE-UA (SPOTPY) | `algorithms/sceua.py` | `--ngs`, `--kstop`, `--peps`, `--pcento` |

**Currently unavailable:** `algorithms/pymoo_nsga2.py` raises `NotImplementedError`; do not advertise NSGA-II as operational. GA and CMA-ES currently require the evaluation budget to be divisible by population size. For custom DDS, check seed conventions: its script currently adds `run_index - 1` to the given seed, while other inspected drivers use the supplied seed directly; this should be harmonized before final release.

## 10. Run multiple basins with Slurm

The tested `exp57/settings/` experiment keeps **scientific TOML**, **optimizer scenario TOML**, **basin manifest**, **Slurm launcher** and **verifier** separate. The current `run_production_array.sh` is FIR- and CENTURY-specific: it expects `SLURM_TMPDIR`, uses one `mpirun -np 1` process per task, creates private state/output directories, records resolved config/metadata, and verifies outputs before writing `completion.json`.

A production invocation has this pattern **after copying/adapting the experiment files and paths**:

```bash
sbatch --array=0-0 \
  --export=ALL,SCENARIO_CONFIG=/path/to/scenario_GA.toml,ALGORITHM=ga \
  /path/to/run_production_array.sh --run
```

Verify the test task before launching an array of remaining case/run indices. Use one independent task per basin/seed; Slurm distributes tasks across available nodes. Do **not** launch a large array directly from a generic example with the existing FIR-specific paths.

## 11. Results and verification

A successful individual optimizer run normally creates:

- `<prefix>_calibration.nc` — native trial-by-trial parameter/objective history (including failed trial flags).
- `<prefix>_sample<N>_trialParams.nc` — best accepted **physical** parameter fields.
- Logs — progress, trial counts, failed/infeasible trials, best score, and errors.

The tested multi-basin Slurm workflow additionally records `resolved_config.toml`, `run_metadata.json` and, **only after NetCDF verification**, `completion.json`. These metadata files belong to the experiment launcher, not the core model API.

The shared optimization score is the weighted mean of `(1 - KGE)` or `(1 - NSE)` for positively weighted targets; zero-weight diagnostics remain in native outputs. Some failed/infeasible candidates are expected in an optimizer and are not synonymous with a failed Slurm job. After calibration, replay the best physical parameters in a normal model run and review streamflow and diagnostics.

## 12. Troubleshooting

| Symptom | Check |
|---|---|
| Missing `summa_py_*` symbols | Installer application, CMake driver source list, clean/reconfigured build |
| `libsumma.so` load error | Matching MPI/NetCDF/SUNDIALS environment and `LD_LIBRARY_PATH` |
| Initialization fails | TOML, input paths, cold state, native model setup, correct outlet/remapping |
| `Permission denied` in `summa_writeOutputFiles` | Writable `state_path` and separate per-task scratch; do not write restarts to shared inputs |
| Excessive trial NetCDF/time-series I/O | `write_timeseries=false`; private model output path |
| Optimizer budget error | GA/CMA population divisibility; SCE-UA initial-complex minimum |
| Existing output blocks rerun | Drivers deliberately refuse overwriting existing NetCDF; inspect/backup before rerun |
| Failed trial count is high | Feasibility constraints, bounds, objective coverage, model errors and penalty logic |

**Release check:** Clean-install and smoke-test this guide on an independent computer/HPC environment before publication. Ray/hybrid MPI benchmarking and legacy DDS benchmark trees are separate developer topics, not prerequisites for this guide.
