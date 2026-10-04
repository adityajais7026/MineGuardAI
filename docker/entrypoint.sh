#!/usr/bin/env bash
# MineGuardAI backend container entrypoint (Render-ready).
#
# 1. If WEIGHTS_URL is set and the configured YOLO weights file is missing,
#    download it once into the persistent disk (survives redeploys/restarts).
#    Weights are NEVER baked into the image and NEVER live in git.
# 1b. Same for the person-anchor (ByteTrack) model: ANCHOR_WEIGHTS_URL ->
#     PERSON_ANCHOR_MODEL_PATH. Without it, the person_anchor strategy raises
#     FileNotFoundError on startup, so this fetch is mandatory when that
#     strategy is enabled (render.yaml sets it for the public deployment).
# 2. Exec uvicorn on 0.0.0.0:$PORT — Render injects PORT per service; the
#    default 8000 keeps local docker runs working unchanged.
set -euo pipefail

PORT="${PORT:-8000}"
WEIGHTS_URL="${WEIGHTS_URL:-}"
WEIGHTS_PATH="${YOLO_MODEL_PATH:-}"

if [ -n "$WEIGHTS_URL" ] && [ -n "$WEIGHTS_PATH" ] && [ ! -f "$WEIGHTS_PATH" ]; then
  echo "[entrypoint] fetching YOLO weights -> $WEIGHTS_PATH"
  mkdir -p "$(dirname "$WEIGHTS_PATH")"
  curl -fsSL --retry 3 -o "$WEIGHTS_PATH" "$WEIGHTS_URL"
  ls -la "$WEIGHTS_PATH"
else
  echo "[entrypoint] weights: using configured file at ${WEIGHTS_PATH:-<unset>}"
fi

ANCHOR_WEIGHTS_URL="${ANCHOR_WEIGHTS_URL:-}"
ANCHOR_PATH="${PERSON_ANCHOR_MODEL_PATH:-}"

if [ -n "$ANCHOR_WEIGHTS_URL" ] && [ -n "$ANCHOR_PATH" ] && [ ! -f "$ANCHOR_PATH" ]; then
  echo "[entrypoint] fetching person-anchor weights -> $ANCHOR_PATH"
  mkdir -p "$(dirname "$ANCHOR_PATH")"
  curl -fsSL --retry 3 -o "$ANCHOR_PATH" "$ANCHOR_WEIGHTS_URL"
  ls -la "$ANCHOR_PATH"
else
  echo "[entrypoint] anchor: using configured file at ${ANCHOR_PATH:-<unset>}"
fi

echo "[entrypoint] starting uvicorn on 0.0.0.0:${PORT}"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
