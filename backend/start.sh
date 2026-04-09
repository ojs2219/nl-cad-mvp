#!/bin/bash
set -e

# ── Virtual display for OpenSCAD headless rendering ──────────────
if [ -z "$DISPLAY" ]; then
    Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
    export DISPLAY=:99
    echo "[start] Xvfb started on :99"
fi

# ── Local static dir (only needed when Supabase Storage is not used) ──
if [ -z "$SUPABASE_URL" ]; then
    SDIR="${STATIC_DIR:-/app/static}"
    mkdir -p "$SDIR/stl" "$SDIR/scad"
    echo "[start] Local static dir: $SDIR"
else
    echo "[start] Supabase Storage enabled — skipping local static dir setup"
fi

# ── Database init (idempotent) ───────────────────────────────────
python3 init_db.py

# ── Launch FastAPI ───────────────────────────────────────────────
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --workers 1 \
    --log-level info
