#!/bin/bash
set -euo pipefail

EXP="/home/armanhad/projects/rrg-mclark/armanhad/hydro_models/experiments/century/MM/exp57"
SCENARIO="$EXP/settings/scenario_GA2.toml"
LAUNCHER="$EXP/settings/run_production_array.sh"

sbatch \
  --job-name=exp57_GA2 \
  --array=0-223%32 \
  --export=ALL,SCENARIO_CONFIG="$SCENARIO",ALGORITHM=ga \
  "$LAUNCHER" --run
