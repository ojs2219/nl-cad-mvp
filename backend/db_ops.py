"""
Database operations abstraction layer.
- When SUPABASE_URL + SUPABASE_SERVICE_KEY are set: uses Supabase REST API (HTTP, IPv4).
- Otherwise: uses SQLAlchemy session (local SQLite).
"""
import os
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Optional

logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")
USE_REST = bool(SUPABASE_URL and SUPABASE_KEY)

_supa = None
if USE_REST:
    try:
        from supabase import create_client
        _supa = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.warning("[db_ops] Supabase REST API mode active")
    except Exception as _e:
        logger.error(f"[db_ops] Failed to init Supabase client: {_e}")
        USE_REST = False

if not USE_REST:
    from database import SessionLocal
    from models import User as _User, Generation as _Generation, SystemPrompt as _SystemPrompt
    logger.warning("[db_ops] SQLAlchemy (SQLite) mode active")


# ── helpers ──────────────────────────────────────────────────────────────────

def _ns(d: Optional[dict]) -> Optional[SimpleNamespace]:
    """Convert dict → SimpleNamespace for attribute access."""
    return SimpleNamespace(**d) if d is not None else None


@contextmanager
def _sa():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ── users ─────────────────────────────────────────────────────────────────────

def get_user_by_email(email: str):
    if USE_REST:
        r = _supa.table("users").select("*").eq("email", email).execute()
        return _ns(r.data[0]) if r.data else None
    with _sa() as db:
        return db.query(_User).filter(_User.email == email).first()


def get_user_by_id(user_id: int):
    if USE_REST:
        r = _supa.table("users").select("*").eq("id", user_id).execute()
        return _ns(r.data[0]) if r.data else None
    with _sa() as db:
        return db.query(_User).filter(_User.id == user_id).first()


def create_user(email: str, hashed_password: str):
    if USE_REST:
        r = _supa.table("users").insert({
            "email": email,
            "hashed_password": hashed_password,
            "is_approved": False,
            "is_admin": False,
        }).execute()
        return _ns(r.data[0])
    with _sa() as db:
        user = _User(email=email, hashed_password=hashed_password,
                     is_approved=False, is_admin=False)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def get_all_users():
    if USE_REST:
        r = _supa.table("users").select("*").order("created_at", desc=True).execute()
        return [_ns(u) for u in r.data]
    with _sa() as db:
        return db.query(_User).order_by(_User.created_at.desc()).all()


def set_user_approved(user_id: int, approved: bool) -> bool:
    if USE_REST:
        r = _supa.table("users").update({"is_approved": approved}).eq("id", user_id).execute()
        return bool(r.data)
    with _sa() as db:
        user = db.query(_User).filter(_User.id == user_id).first()
        if not user:
            return False
        user.is_approved = approved
        db.commit()
        return True


def update_custom_prompt(user_id: int, custom_prompt: Optional[str]):
    if USE_REST:
        _supa.table("users").update({"custom_prompt": custom_prompt}).eq("id", user_id).execute()
        return
    with _sa() as db:
        user = db.query(_User).filter(_User.id == user_id).first()
        if user:
            user.custom_prompt = custom_prompt
            db.commit()


# ── system prompt ─────────────────────────────────────────────────────────────

def get_system_prompt():
    if USE_REST:
        r = _supa.table("system_prompts").select("*").eq("name", "main").execute()
        return _ns(r.data[0]) if r.data else None
    with _sa() as db:
        return db.query(_SystemPrompt).filter(_SystemPrompt.name == "main").first()


def set_system_prompt(content: str):
    """Update system prompt content. Returns the updated object."""
    from datetime import datetime, timezone
    if USE_REST:
        _supa.table("system_prompts").update({
            "content": content,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("name", "main").execute()
        return get_system_prompt()
    with _sa() as db:
        p = db.query(_SystemPrompt).filter(_SystemPrompt.name == "main").first()
        if p:
            p.content = content
            db.commit()
            db.refresh(p)
        return p


# ── generations ───────────────────────────────────────────────────────────────

def create_generation(user_id: int, input_text: str):
    if USE_REST:
        r = _supa.table("generations").insert({
            "user_id": user_id,
            "input_text": input_text,
            "status": "pending",
        }).execute()
        return _ns(r.data[0])
    with _sa() as db:
        gen = _Generation(user_id=user_id, input_text=input_text, status="pending")
        db.add(gen)
        db.commit()
        db.refresh(gen)
        return gen


def update_generation(gen_id: int, **kwargs):
    if USE_REST:
        _supa.table("generations").update(kwargs).eq("id", gen_id).execute()
        return
    with _sa() as db:
        gen = db.query(_Generation).filter(_Generation.id == gen_id).first()
        if gen:
            for k, v in kwargs.items():
                setattr(gen, k, v)
            db.commit()


def get_generation_by_id(gen_id: int, user_id: int):
    if USE_REST:
        r = _supa.table("generations").select("*").eq("id", gen_id).eq("user_id", user_id).execute()
        return _ns(r.data[0]) if r.data else None
    with _sa() as db:
        return db.query(_Generation).filter(
            _Generation.id == gen_id, _Generation.user_id == user_id
        ).first()


def get_user_generations(user_id: int, limit: int = 50):
    if USE_REST:
        r = (_supa.table("generations").select("*")
             .eq("user_id", user_id)
             .order("created_at", desc=True)
             .limit(limit)
             .execute())
        return [_ns(g) for g in r.data]
    with _sa() as db:
        return (db.query(_Generation)
                .filter(_Generation.user_id == user_id)
                .order_by(_Generation.created_at.desc())
                .limit(limit).all())


def delete_generation(gen_id: int, user_id: int) -> bool:
    if USE_REST:
        r = _supa.table("generations").delete().eq("id", gen_id).eq("user_id", user_id).execute()
        return True
    with _sa() as db:
        gen = db.query(_Generation).filter(
            _Generation.id == gen_id, _Generation.user_id == user_id
        ).first()
        if not gen:
            return False
        db.delete(gen)
        db.commit()
        return True


def get_all_generations(limit: int = 200):
    """Returns generations with an extra `user_email` attribute."""
    if USE_REST:
        r = (_supa.table("generations")
             .select("*, users(email)")
             .order("created_at", desc=True)
             .limit(limit)
             .execute())
        result = []
        for g in r.data:
            d = dict(g)
            user_data = d.pop("users", None)
            d["user_email"] = user_data.get("email") if isinstance(user_data, dict) else None
            result.append(_ns(d))
        return result
    with _sa() as db:
        gens = (db.query(_Generation)
                .order_by(_Generation.created_at.desc())
                .limit(limit).all())
        for g in gens:
            g.user_email = g.user.email if g.user else None
        return gens
