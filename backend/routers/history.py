from fastapi import APIRouter, Depends, HTTPException
from typing import List
from schemas import GenerationOut
from auth import get_approved_user
import db_ops

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


@router.get("/", response_model=List[GenerationOut])
def get_history(current_user=Depends(get_approved_user)):
    records = db_ops.get_user_generations(current_user.id)
    return [_to_out(r) for r in records]


@router.get("/{generation_id}", response_model=GenerationOut)
def get_generation(generation_id: int, current_user=Depends(get_approved_user)):
    gen = db_ops.get_generation_by_id(generation_id, current_user.id)
    if not gen:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    return _to_out(gen)


@router.delete("/{generation_id}")
def delete_generation(generation_id: int, current_user=Depends(get_approved_user)):
    if not db_ops.delete_generation(generation_id, current_user.id):
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    return {"message": "삭제되었습니다."}
