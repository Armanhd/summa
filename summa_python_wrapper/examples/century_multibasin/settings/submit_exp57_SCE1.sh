#!/bin/bash
set -euo pipefail

EXP="/home/armanhad/projects/rrg-mclark/armanhad/hydro_models/experiments/century/MM/exp57"

sbatch \
  --job-name=exp57_SCE1 \
  --array=0-223%12 \
  --mem=16G \
  --export=ALL,SCENARIO_CONFIG="$EXP/settings/scenario_SCE1.toml",ALGORITHM=sceua \
  "$EXP/settings/run_production_array.sh" --run
