from fastapi import APIRouter, Depends, HTTPException
from schemas import GenerateRequest, GenerationOut
from auth import get_approved_user
from services.ai_service import parse_input
from services.scad_generator import generate_scad_code
from services.cad_service import generate_stl
from services.storage_service import upload_stl
import db_ops
import json
import uuid
import os
import tempfile

router = APIRouter()


def _to_out(gen) -> dict:
    return {
        "id": gen.id,
        "input_text": gen.input_text,
        "params_json": gen.params_json,
        "scad_code": gen.scad_code,
        "stl_url": gen.stl_url,
        "status": gen.status,
        "error_message": gen.error_message,
        "created_at": gen.created_at,
    }


@router.post("/generate", response_model=GenerationOut)
async def generate(request: GenerateRequest, current_user=Depends(get_approved_user)):
    if not request.input_text.strip():
        raise HTTPException(status_code=422, detail="입력값이 비어 있습니다.")

    sys_prompt_row = db_ops.get_system_prompt()
    system_prompt_text = sys_prompt_row.content if sys_prompt_row else None

    gen = db_ops.create_generation(user_id=current_user.id, input_text=request.input_text)

    try:
        params = await parse_input(
            request.input_text,
            system_prompt=system_prompt_text,
            user_prompt=current_user.custom_prompt,
        )
        params_json = json.dumps(params, ensure_ascii=False)
        scad_code = generate_scad_code(params)

        uid = uuid.uuid4().hex
        stl_filename = f"{uid}.stl"

        with tempfile.TemporaryDirectory() as tmpdir:
            scad_path = os.path.join(tmpdir, f"{uid}.scad")
            tmp_stl = os.path.join(tmpdir, stl_filename)
            generate_stl(scad_code, scad_path, tmp_stl)
            stl_url = upload_stl(stl_filename, tmp_stl)

        db_ops.update_generation(
            gen.id,
            params_json=params_json,
            scad_code=scad_code,
            stl_url=stl_url,
            status="success",
        )

    except ValueError as e:
        db_ops.update_generation(gen.id, status="failed", error_message=str(e))
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        db_ops.update_generation(gen.id, status="failed", error_message=str(e))
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        msg = f"서버 오류가 발생했습니다: {e}"
        db_ops.update_generation(gen.id, status="failed", error_message=msg)
        raise HTTPException(status_code=500, detail=msg)

    updated = db_ops.get_generation_by_id(gen.id, current_user.id)
    return _to_out(updated)
