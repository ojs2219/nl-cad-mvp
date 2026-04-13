"""File storage — Supabase Storage (production) or local filesystem (dev)."""
import os
import shutil
from supabase_client import get_supabase

STL_BUCKET = "stl-files"
IR_BUCKET  = "stl-files"   # reuse same bucket; IR files go in ir/ prefix


def upload_stl(filename: str, tmp_path: str) -> str:
    """Upload an STL file and return its publicly accessible URL."""
    sb = get_supabase()
    if sb:
        with open(tmp_path, "rb") as f:
            data = f.read()
        sb.storage.from_(STL_BUCKET).upload(
            filename,
            data,
            file_options={"content-type": "application/octet-stream", "upsert": "true"},
        )
        return sb.storage.from_(STL_BUCKET).get_public_url(filename)

    # Local fallback
    static_dir = os.getenv("STATIC_DIR", "static")
    dest = os.path.join(static_dir, "stl", filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copy2(tmp_path, dest)
    return f"/static/stl/{filename}"


def upload_ir_json(filename: str, json_str: str) -> str:
    """Upload IR JSON and return its publicly accessible URL (or local path)."""
    sb = get_supabase()
    if sb:
        data = json_str.encode("utf-8")
        ir_path = f"ir/{filename}"
        sb.storage.from_(IR_BUCKET).upload(
            ir_path,
            data,
            file_options={"content-type": "application/json", "upsert": "true"},
        )
        return sb.storage.from_(IR_BUCKET).get_public_url(ir_path)

    # Local fallback
    static_dir = os.getenv("STATIC_DIR", "static")
    dest = os.path.join(static_dir, "ir", filename)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(json_str)
    return f"/static/ir/{filename}"


def delete_stl(stl_url: str) -> None:
    """Best-effort deletion from Supabase Storage or local filesystem."""
    if not stl_url:
        return
    sb = get_supabase()
    if sb and stl_url.startswith("http"):
        filename = stl_url.rsplit("/", 1)[-1].split("?")[0]
        try:
            sb.storage.from_(STL_BUCKET).remove([filename])
        except Exception:
            pass
    elif not stl_url.startswith("http"):
        local_path = stl_url.lstrip("/")
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except OSError:
                pass
