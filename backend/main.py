import os
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers import auth, generate, admin, history

# Startup: try to initialize DB (non-fatal)
try:
    import init_db
    init_db.main()
except Exception as _e:
    import logging
    logging.warning(f"[startup] init_db failed: {_e}")

app = FastAPI(title="NL-CAD API", version="1.0.0")

# CORS
_raw_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]
_origin_regex = os.getenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Local static file serving — only when Supabase Storage is NOT configured
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
    return {"status": "ok", "version": "ir-composable-v2"}


@app.get("/api/debug/db")
def debug_db():
    """Temporary debug endpoint."""
    import db_ops
    result = {"mode": "rest_api" if db_ops.USE_REST else "sqlalchemy"}
    try:
        u = db_ops.get_user_by_email("admin@example.com")
        result["admin_found"] = bool(u)
        if u:
            result["admin_email"] = u.email
    except Exception as e:
        result["error"] = str(e)[:300]
    return result
