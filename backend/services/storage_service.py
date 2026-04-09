"""STL file storage — Supabase Storage (production) or local filesystem (dev fallback)."""
import os
import shutil
from supabase_client import get_supabase

BUCKET = "stl-files"


def upload_stl(filename: str, tmp_path: str) -> str:
    """Upload an STL file and return its publicly accessible URL.

    - If Supabase is configured → uploads to Supabase Storage, returns CDN URL.
    - Otherwise → copies to local static/stl/, returns /static/stl/<filename>.
    """
    sb = get_supabase()

    if sb:
        with open(tmp_path, "rb") as f:
            data = f.read()
        # upsert=true overwrites existing file with the same name
        sb.storage.from_(BUCKET).upload(
            filename,
            data,
            file_options={
                "content-type": "application/octet-stream",
                "upsert": "true",
            },
        )
        return sb.storage.from_(BUCKET).get_public_url(filename)

    # Local fallback: copy to STATIC_DIR/stl/
    static_dir = os.getenv("STATIC_DIR", "static")
    dest = os.path.join(static_dir, "stl", filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(tmp_path, dest)
    return f"/static/stl/{filename}"


def delete_stl(stl_url: str) -> None:
    """Best-effort deletion from Supabase Storage (or local filesystem)."""
    if not stl_url:
        return

    sb = get_supabase()
    if sb and stl_url.startswith("http"):
        # Extract filename from URL tail
        filename = stl_url.rsplit("/", 1)[-1]
        try:
            sb.storage.from_(BUCKET).remove([filename])
        except Exception:
            pass
    elif not stl_url.startswith("http"):
        # Local file — strip /static/stl/ prefix
        local_path = stl_url.lstrip("/")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
