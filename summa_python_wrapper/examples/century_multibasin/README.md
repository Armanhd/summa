# CENTURY multibasin calibration examples

These examples originate from the exp57 SUMMA calibration experiments.

Supported algorithms include GA, DE, CMA-ES, SCE-UA,
custom DDS and SPOTPY DDS.

The scripts are provided as reference implementations.

IMPORTANT:
- Replace FIR-specific paths before execution.
- Provide your own basin manifest and SUMMA input files.
- Configure the SUMMA shared library location.
- Review scenario TOML files before submitting Slurm jobs.
- The examples have not yet been validated on another system.
