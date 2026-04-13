from fastapi import APIRouter, Depends, HTTPException
from schemas import GenerateRequest, ModifyRequest, GenerationOut
from auth import get_approved_user
from services.ir.parser import parse_to_ir
from services.ir.modifier import modify_ir
from services.ir.resolver import resolve
from services.generators.openscad import OpenSCADGenerator
from services.cad_service import generate_stl
from services.storage_service import upload_stl, upload_ir_json
import db_ops
import uuid
import os
import tempfile

router = APIRouter()
_generator = OpenSCADGenerator()


def _to_out(gen) -> dict:
    return {
        "id": gen.id,
        "input_text": gen.input_text,
        "params_json": getattr(gen, "params_json", None),
        "ir_json": getattr(gen, "ir_json", None),
        "scad_code": getattr(gen, "scad_code", None),
        "stl_url": getattr(gen, "stl_url", None),
        "status": gen.status,
        "error_message": getattr(gen, "error_message", None),
        "created_at": gen.created_at,
        "parent_id": getattr(gen, "parent_id", None),
    }


async def _run_pipeline(
    input_text: str,
    current_user,
    parent_id: int | None = None,
    existing_ir=None,
    modification_text: str | None = None,
):
    """
    Shared generation pipeline.

    - If existing_ir + modification_text → modify existing IR, then re-generate.
    - Otherwise → parse NL to IR, then generate.
    """
    sys_prompt_row = db_ops.get_system_prompt()
    system_prompt_text = sys_prompt_row.content if sys_prompt_row else None

    gen = db_ops.create_generation(
        user_id=current_user.id,
        input_text=input_text,
        parent_id=parent_id,
    )

    try:
        # ── 1. IR acquisition ─────────────────────────────────────────────────
        if existing_ir and modification_text:
            ir_tree = await modify_ir(existing_ir, modification_text)
        else:
            ir_tree = await parse_to_ir(
                input_text,
                system_prompt=system_prompt_text,
                user_prompt=getattr(current_user, "custom_prompt", None),
            )

        # ── 1b. Resolve semantic relation nodes → concrete geometry ───────────
        ir_tree = resolve(ir_tree)

        ir_json_str = ir_tree.to_json()

        # ── 2. Code generation ────────────────────────────────────────────────
        scad_code = _generator.generate_code(ir_tree)

        # ── 3. STL generation ─────────────────────────────────────────────────
        uid = uuid.uuid4().hex
        stl_filename = f"{uid}.stl"
        ir_filename  = f"{uid}.json"

        with tempfile.TemporaryDirectory() as tmpdir:
            scad_path = os.path.join(tmpdir, f"{uid}.scad")
            tmp_stl   = os.path.join(tmpdir, stl_filename)
            generate_stl(scad_code, scad_path, tmp_stl)
            stl_url = upload_stl(stl_filename, tmp_stl)

        # Upload IR JSON (best-effort, non-fatal)
        try:
            upload_ir_json(ir_filename, ir_json_str)
        except Exception:
            pass

        db_ops.update_generation(
            gen.id,
            ir_json=ir_json_str,
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


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/generate", response_model=GenerationOut)
async def generate(request: GenerateRequest, current_user=Depends(get_approved_user)):
    if not request.input_text.strip():
        raise HTTPException(status_code=422, detail="입력값이 비어 있습니다.")
    return await _run_pipeline(request.input_text, current_user)


@router.post("/modify/{generation_id}", response_model=GenerationOut)
async def modify(
    generation_id: int,
    request: ModifyRequest,
    current_user=Depends(get_approved_user),
):
    """Apply a NL modification request to an existing generation's IR tree."""
    if not request.modification_text.strip():
        raise HTTPException(status_code=422, detail="수정 내용이 비어 있습니다.")

    original = db_ops.get_generation_by_id(generation_id, current_user.id)
    if not original:
        raise HTTPException(status_code=404, detail="원본 생성 기록을 찾을 수 없습니다.")
    if not getattr(original, "ir_json", None):
        raise HTTPException(status_code=400, detail="이 기록에는 IR 데이터가 없습니다. 먼저 새로 생성해 주세요.")

    from services.ir.schema import IRTree
    existing_ir = IRTree.from_json(original.ir_json)

    return await _run_pipeline(
        input_text=original.input_text,   # preserve original prompt
        current_user=current_user,
        parent_id=generation_id,
        existing_ir=existing_ir,
        modification_text=request.modification_text,
    )
