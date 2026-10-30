#!/usr/bin/env bash
# Rebuilds every PeoplePulse output from data/raw/PeoplePulse_IBM_Integrated.xlsx.
set -euo pipefail
cd "$(dirname "$0")/src"
for s in 01_ingest 02_synthetic 03_build_model 04_attrition 05_workforce 06_export 07_deck; do
  echo "== $s"; python3 "$s.py"
done
