# SUMMA Python Wrapper — Development and Integration Notes

> **Status:** Draft based on the November 2026 FIR source inventory. This documents what the standalone wrapper **currently contains**, what the installer changes in a compatible SUMMA checkout, and what must be verified before proposing an upstream PR. Older v4.5 documentation is not an authoritative description of the current code.

## 1. Architecture and responsibility

```text
Python optimizer (DDS / GA / DE / CMA-ES / SCE-UA)
  -> common ParameterSpace and SummaEvaluator (GA currently uses its own evaluator)
  -> python_wrapper/summa_ctypes.py
  -> libsumma.so : C ABI defined by fortran_api/summa_python_api.f90
  -> native SUMMA calibration, coupled SUMMA-mizuRoute evaluation, native NetCDF
```

**SUMMA owns** configuration, parameter names/bounds and log transformations, parameter dependencies/ratios/spatial multipliers, physical feasibility, spin-up, model evaluation, objective calculations, NetCDF calibration output and export of best physical parameter fields. **Python owns** candidate generation, algorithms, run seeds, scores for algorithm consumption, trial bookkeeping and scheduling. Each Python process owns one initialized SUMMA worker; SUMMA global state is not assumed thread-safe.

The Fortran API calls MPI with `MPI_COMM_SELF` for an independent model worker. This **does not** mean that the coupled wrapper currently decomposes one model simulation across multiple MPI ranks. The validated exp57 launcher uses `mpirun -np 1` per Slurm task.

## 2. Current source files and roles

| Repository path | Status / purpose |
|---|---|
| `fortran_api/summa_python_api.f90` | **Required.** Thin C ABI to SUMMA calibration implementation |
| `install_wrapper.py` | **Required.** Install that API into compatible SUMMA tree and modify two CMake files; default dry-run |
| `python_wrapper/summa_ctypes.py` | **Required.** Python ctypes signatures and `SummaModel` lifecycle/output operations |
| `python_wrapper/parameter_space.py` | **Required.** Convert search, physical, and normalized parameter coordinates; bounds from SUMMA |
| `python_wrapper/optimization_core.py` | **Required for current DDS/DE/CMA-ES/SCE-UA.** Shared `SummaEvaluator`, weighting, failed-trial handling and NetCDF recording |
| `python_wrapper/pymoo_calibration/calibration_config.py` | **Required.** Parse scientific calibration TOML and multibasin manifest |
| `python_wrapper/pymoo_calibration/run_calibration.py` | **Required for GA.** Current pymoo GA runner; still has local objective/evaluator logic |
| `python_wrapper/algorithms/custom_dds.py` | **Required for custom DDS.** Uses `dds_optimiser.py` candidate generator |
| `python_wrapper/dds_optimiser.py` | **Required for custom DDS.** Existing DDS sampling logic; also supports older workflows |
| `python_wrapper/algorithms/spotpy_dds.py` | **Required for SPOTPY DDS and SCE-UA.** Shared adapter, selection via `run()` |
| `python_wrapper/algorithms/sceua.py` | **Required for SCE-UA.** Small forwarding entry point into `spotpy_dds.run("sceua")` |
| `python_wrapper/run_de_calibration.py` | **Required for DE.** SciPy differential evolution runner |
| `python_wrapper/run_cmaes_calibration.py` | **Required for CMA-ES.** CMA package runner |
| `python_wrapper/algorithms/pymoo_nsga2.py` | **Placeholder.** Raises `NotImplementedError`; not a tested optimizer |
| `python_wrapper/test_single_evaluation.py`, `test_pr675_*.py` | Validation/diagnostic scripts; select reproducible ones for `tests/` |
| `python_wrapper/parallel/` | Optional multiprocessing preparation and smoke tests; not the exp57 production backend |
| `python_wrapper/hybrid_ray_mpi/`, `dds_ray_optimiser.py`, `summa_ray_worker.py`, `ray_dds_launcher.py` | Optional/experimental distributed scheduling and Ray/MPI workflows; must be inventoried separately before public release |
| `python_wrapper/python_dds_benchmarks/` | Research benchmarking; includes vendored third-party code and generated per-task configurations; **do not publish wholesale** |
| `utils/` | Existing support utilities; include selectively after confirming runtime dependencies |

Old `.before_*` files, caches, Slurm logs, generated experiment results, per-task resolved configs, installed third-party `vendor/` trees, binaries and scratch files are not source deliverables.

## 3. Fortran API: exposed functions

`summa_python_api.f90` exports these 14 C-bindable functions:

| C symbol | Purpose |
|---|---|
| `summa_py_api_version` | Report wrapper API revision (`675` in current source) |
| `summa_py_set_run_index` | Select independent run index before initialization |
| `summa_py_init` | Initialize MPI context, parse SUMMA TOML, full-domain run mode, spin-up and native calibration adapter |
| `summa_py_nparameters` | Number of sampled parameters |
| `summa_py_get_parameter` | Parameter name, transform, physical and search bounds |
| `summa_py_check_feasibility` | Native parameter constraints |
| `summa_py_evaluate` | Native coupled simulation and objective evaluation |
| `summa_py_get_defaults` | Get physical initial/default candidate values |
| `summa_py_set_optimizer` | Set optimizer name in native output |
| `summa_py_output_open` | Create native calibration NetCDF |
| `summa_py_output_write` | Append attempted candidate, objectives, failure flag and timestamps |
| `summa_py_output_close` | Close calibration NetCDF |
| `summa_py_export_best` | Export best feasible physical parameter fields |
| `summa_py_finalize` | Finalize MPI if owned by the wrapper |

Count the individual `public ::` declarations rather than relying on old inventories. Note that `summa_py_finalize` currently handles MPI finalization, not a demonstrated full reset of all saved Fortran module state; assume one initialization per worker process.

## 4. Exact SUMMA changes made by `install_wrapper.py`

On a **compatible SUMMA calibration checkout** (not an arbitrary SUMMA release), `python install_wrapper.py --summa-source "$SUMMA" --apply` performs:

1. **New file:** `SUMMA/build/source/driver/python_api/summa_python_api.f90` — copied from wrapper `fortran_api/`.
2. **Edit:** `SUMMA/build/source/CMakeLists.txt` — adds `${DRIVER_DIR}/python_api/summa_python_api.f90` immediately before the known `summa_spinup.f90` anchor.
3. **Edit:** `SUMMA/build/CMakeLists.txt` — adds conditional MPI linkage `target_link_libraries(summa PRIVATE PARALLEL_UTILS MPI::MPI_Fortran)` under `if (USE_MPI)` at a verified anchor.

The installer checks the marker `SUMMA_PY_API_PR675`, requires both CMake anchors, avoids duplicate entries and supports a dry-run. It **does not** build SUMMA, install Python packages, or install the native calibration implementation on which this API depends.

**Important upstream integration boundary:** `summa_python_api.f90` calls calibration modules and procedures such as `initialize_parameter_search`, `initialize_summa_calibration_adapter`, `evaluate_objectives`, and `write_physical_trial_parameters`. Before a PR, confirm that all of them exist in the selected `CH-Earth/summa` target branch. If not, those upstream dependencies need their own documented integration or an agreed base commit. The three-file installer change alone is not evidence that stock `develop` can compile the wrapper.

## 5. Verified FIR build details

Environment loader `summa_vpr675_python/load_model_env_fir.sh` uses `StdEnv/2023`, `gcc/12.3`, `openmpi/4.1.5`, `netcdf/4.9.2`, `netcdf-fortran/4.6.1`, `cmake/3.31.0`, `openblas/0.3.24`, plus local SUNDIALS `7.3.0` (`SUNDIALS_ROOT` and `SUNDIALS_DIR`). It fixes numerical thread counts to 1.

The verified `builds/summa_vpr675_python/build_summa.sh` compiles with `-DUSE_MPI=ON`, `-DUSE_SUNDIALS=ON`, `-DUSE_MIZUROUTE=ON`, `-DUSE_TOML=ON`, `-DCMAKE_POSITION_INDEPENDENT_CODE=ON`, `-DCMAKE_BUILD_TYPE=Release`, and `-ffree-line-length-none`; then executes `cmake --build "$BUILD" --target summa --parallel 8`. CMake cache shows `BUILD_SHARED_LIBS=OFF`, but the target produces `libsumma.so`. The inspected shared library was present at `builds/summa_vpr675_python/libsumma.so`; test its exported symbols with `nm -D`.

**Reproducibility note:** FIR module versions and absolute compiler paths should be retained as an example, not hardcoded into the published installer. Document the compatible SUMMA source commit, SUNDIALS, compiler/MPI and linkage as a tested combination.

## 6. Calibration configuration and execution

- **SUMMA scientific TOML** controls inputs, periods, targets/weights, parameter metadata and objective calculation. `calibration_config.py` only parses metadata; it does not replace native parameter definitions.
- **Optimizer scenario TOML** supplies algorithm settings, evaluation budget and independent seed base.
- **Manifest TOML** maps cases × independent runs to array indices.
- **Slurm launcher** stages private node-local scratch, points `state_path` at a writable directory containing a symlink to `coldState.nc`, redirects model `output_path`, passes a concrete SUMMA TOML and executes one Python optimization via `mpirun -np 1`.
- **Verifier** checks calibration/best-parameter NetCDF files before the launcher writes `completion.json`.

The current `experiments/century/MM/exp57/settings/run_production_array.sh` is a validated **research-specific launcher**, not yet portable. Publish a sanitized, independently tested example instead of copying its FIR paths, CENTURY case assumptions and Slurm account/partition values directly.

## 7. Objective values and output

`optimization_core.py` maps each positive-weight KGE/NSE target to `1 - metric`; it takes their weighted mean for single-objective optimizers. Zero-weight targets are excluded from the search score but retained in native output. Infeasible/failed trials are penalized (`1e6`), recorded and counted separately from attempted SUMMA simulations. GA currently duplicates this evaluator logic locally; keep behavior consistent until a tested refactor.

Current primary outputs: `<prefix>_calibration.nc` (native calibration history) and `<prefix>_sample<N>_trialParams.nc` (best physical parameter fields). Experiment launcher outputs additionally include resolved scientific TOML, metadata, completion marker and Slurm logs. Old v4.5 JSON/CSV output claims do not describe this production implementation.

## 8. Known constraints and release checks

- **Algorithm readiness:** GA, custom DDS, SPOTPY DDS, SciPy DE, CMA-ES and SPOTPY SCE-UA have implemented drivers; NSGA-II remains a placeholder.
- **Budget handling:** GA/CMA-ES require `budget % population_size == 0`. SCE-UA requires a sufficiently large initial complex. Verify completed counts and native output for every algorithm.
- **Seed consistency:** Custom DDS currently calculates `seed = args.seed + args.run_index - 1`; GA/DE/CMA-ES/SPOTPY use `args.seed`. The production launcher already assigns a run-specific seed. Harmonize and regression-test this before publishing reproducibility claims across algorithms.
- **I/O:** Native spin-up and trial simulation can still perform substantial repeated initialization/I/O. Do not claim all static model inputs remain resident between trials.
- **MPI/parallelism:** `MPI_COMM_SELF` isolates independent processes; Ray/hybrid outer/inner MPI is optional and needs separate benchmarks/validation. Never assume thread safety.
- **State:** Every task needs a private writable restart and working directory. The working exp57 launcher addresses the previously observed `Permission denied` restart issue.
- **Testing:** On a clean environment, verify installer dry run/application, compilation and exported symbols, a single evaluation, each optimizer's small budget, NetCDF schema/best field export, two seeds, and a Slurm two-task pilot.
- **Repository hygiene:** Exclude `vendor/` copies (subject to license review), `*.before_*`, logs, result NetCDF, task-specific TOML, caches, `.so`, virtual environments, scratch and HPC paths. Preserve original FIR experiments separately.

## 9. Git integration plan

1. Publish the independent `summa_python_wrapper` repository under the developer's GitHub account, without SUMMA source duplication; include source, installer, tested example configurations, tests, and concise documentation.
2. Have a colleague perform clean setup and reproduce small single-basin and multi-basin tests.
3. Open an upstream feature discussion/issue describing the Python C ABI and native calibration dependency requirements.
4. Create a dedicated branch in a **fork of `CH-Earth/summa`** based on the maintainers' agreed base (`develop` is the likely integration target; confirm before preparing the PR).
5. Apply the required source/API/CMake additions and (if needed) compatible native calibration dependencies. Use GitHub's generated PR diff against the agreed base. Avoid changing production experiments in the process.

**Before release**, inventory `utils/`, test scripts and optional Ray/MPI workflows against the real imports so that the final published tree is minimal and accurate. Do not move the working scripts until tests cover the new imports.
