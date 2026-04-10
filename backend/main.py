import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from database import engine
from models import Base
from routers import auth, generate, admin, history

try:
    Base.metadata.create_all(bind=engine)
except Exception as _e:
    import logging
    logging.warning(f"[startup] DB create_all failed (will retry on first request): {_e}")

app = FastAPI(title="NL-CAD API", version="1.0.0")

# CORS: explicit origins + optional regex for Vercel preview URLs
_raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
# CORS_ORIGIN_REGEX: allows all *.vercel.app by default; set to "" to disable
_origin_regex = os.getenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local static file serving — only active when Supabase Storage is NOT configured.
# In production with Supabase, STL files live in Supabase Storage (no local mount needed).
_use_local_static = not os.getenv("SUPABASE_URL", "").strip()
STATIC_DIR = os.getenv("STATIC_DIR", "static")
if _use_local_static:
    os.makedirs(f"{STATIC_DIR}/stl", exist_ok=True)
    os.makedirs(f"{STATIC_DIR}/scad", exist_ok=True)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(generate.router, prefix="/api", tags=["generate"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/debug/db")
def debug_db():
    """Temporary debug endpoint — remove after DB issue resolved."""
    import traceback, urllib.request
    results = {}

    # 1. Test SQLAlchemy direct connection
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        results["sqlalchemy"] = "connected"
    except Exception as e:
        results["sqlalchemy"] = f"error: {str(e)[:200]}"

    # 2. Test Supabase REST API from Render
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if supabase_url and supabase_key:
        try:
            req = urllib.request.Request(
                f"{supabase_url}/rest/v1/users?limit=1",
                headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()
            results["rest_api"] = f"connected, got {len(body)} bytes"
        except Exception as e:
            results["rest_api"] = f"error: {str(e)[:200]}"
    else:
        results["rest_api"] = "not configured"

    return results
