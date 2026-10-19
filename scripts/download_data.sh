#!/usr/bin/env bash
# Download the FlyWire FAFB v783 tables used by this project (~270 MB).
# connections_no_threshold has every synapse; connections.csv.gz (rows with
# >= 5 synapses) is kept for comparison: see scripts/extract_mb_circuit.py.
# Data license: CC BY-NC 4.0 — non-commercial use, attribution required.
# Cite: Dorkenwald et al. 2024 and Schlegel et al. 2024 (Nature).
set -euo pipefail

DEST="${1:-data/raw}"
BASE="https://storage.googleapis.com/flywire-data/codex/data/fafb/783"
FILES=(classification.csv.gz consolidated_cell_types.csv.gz connections_no_threshold.csv.gz
       connections.csv.gz coordinates.csv.gz)

mkdir -p "$DEST"
for f in "${FILES[@]}"; do
  if [[ -f "$DEST/$f" ]]; then
    echo "skip  $f (already present)"
  else
    echo "fetch $f"
    curl -fL --progress-bar -o "$DEST/$f" "$BASE/$f"
  fi
done
ls -lh "$DEST"