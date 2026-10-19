#!/usr/bin/env bash
# Assemble a Hugging Face Docker Space from the committed code (HEAD):
#
#   bash deploy/huggingface/prepare.sh build/hf-space
#   cd build/hf-space && git init -b main && git add -A && git commit -m "fruit_fly demo"
#   git remote add space https://huggingface.co/spaces/<user>/<space> && git push --force space main
#
# The Space builds the repository's Dockerfile with the real FlyWire circuit,
# runs as user 1000 (as Spaces require), and adds limits for a shared public demo.
set -euo pipefail

OUT="${1:?usage: prepare.sh OUTPUT_DIR}"
ROOT="$(git rev-parse --show-toplevel)"
HERE="$ROOT/deploy/huggingface"

if [[ ! -s "$ROOT/deploy/params/flywire.json" ]]; then
  echo "deploy/params/flywire.json is missing: run the FlyWire validation with --calibrate first" >&2
  exit 1
fi
if [[ -n "$(git -C "$ROOT" status --porcelain)" ]]; then
  echo "note: uncommitted changes are NOT included (the Space is built from HEAD)" >&2
fi

rm -rf "$OUT"
mkdir -p "$OUT"
git -C "$ROOT" archive HEAD | tar -x -C "$OUT"

# The Space card (front matter tells Hugging Face how to run it) replaces the README.
cp "$HERE/README.md" "$OUT/README.md"

# Build-time choices: the real circuit, and the user id Spaces run containers as.
sed -i.bak -e 's/^ARG CIRCUIT=.*/ARG CIRCUIT=flywire/' -e 's/^ARG APP_UID=.*/ARG APP_UID=1000/' "$OUT/Dockerfile"
rm "$OUT/Dockerfile.bak"
grep -q '^ARG CIRCUIT=flywire$' "$OUT/Dockerfile" && grep -q '^ARG APP_UID=1000$' "$OUT/Dockerfile" \
  || { echo "could not set the build arguments in the Dockerfile" >&2; exit 1; }

# Limits for a shared public demo (see backend/app/config.py for each setting).
cat >> "$OUT/Dockerfile" <<'EOF'

# ---- public demo (added by deploy/huggingface/prepare.sh)
# Requests arrive through the Spaces proxy: take the visitor's address from the
# X-Forwarded-For entry it appends, so rate limits and ownership apply per visitor.
# A sweep is charged one per experiment, so the sweep size stays within the
# per-minute limit; the queue holds two full sweeps.
ENV FRUIT_FLY_PROXY_HOPS=1 \
    FRUIT_FLY_RATE_LIMIT=12 \
    FRUIT_FLY_MAX_SWEEP_SIZE=12 \
    FRUIT_FLY_MAX_PENDING=24 \
    FRUIT_FLY_MAX_EXPERIMENTS=300 \
    FRUIT_FLY_MAX_WORKERS=2
EOF

echo "Space ready in $OUT"
