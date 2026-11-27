#!/bin/bash
set -euo pipefail

EXP="/home/armanhad/projects/rrg-mclark/armanhad/hydro_models/experiments/century/MM/exp57"

sbatch \
  --job-name=exp57_DE1 \
  --array=1-223%64 \
  --export=ALL,SCENARIO_CONFIG="$EXP/settings/scenario_DE1.toml",ALGORITHM=de \
  "$EXP/settings/run_production_array.sh" --run
