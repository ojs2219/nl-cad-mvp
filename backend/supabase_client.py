"""Lazy-initialized Supabase client.

Returns None when SUPABASE_URL / SUPABASE_SERVICE_KEY are not set,
so the app gracefully falls back to local SQLite + filesystem.
"""
import os
from typing import Optional

_client = None


def get_supabase():
    """Return a Supabase client, or None if credentials are not configured."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

    if not (url and key):
        return None

    try:
        from supabase import create_client
        _client = create_client(url, key)
        return _client
    except ImportError:
        return None
