#!/usr/bin/env bash
# Download the DoOR 2.0 odour-response database (Münch & Galizia 2016, Sci Rep 6:21841).
# License: CC BY-SA 4.0 — attribution required, share-alike.
# Only the three tables the simulator needs are kept.
set -euo pipefail

DEST="${1:-data/raw/door}"
URL="https://codeload.github.com/ropensci/DoOR.data/zip/refs/heads/master"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$DEST"
echo "fetch DoOR.data"
curl -fL --progress-bar -o "$TMP/door.zip" "$URL"
unzip -q "$TMP/door.zip" -d "$TMP"
for f in door_response_matrix.csv door_mappings.csv odor.csv; do
  cp "$TMP"/DoOR.data-master/data/"$f" "$DEST/"
done
ls -lh "$DEST"
