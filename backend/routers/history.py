from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import User, Generation
from schemas import GenerationOut
from auth import get_approved_user

router = APIRouter()


def _to_out(gen: Generation) -> dict:
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
def get_history(current_user: User = Depends(get_approved_user), db: Session = Depends(get_db)):
    records = (
        db.query(Generation)
        .filter(Generation.user_id == current_user.id)
        .order_by(Generation.created_at.desc())
        .all()
    )
    return [_to_out(r) for r in records]


@router.get("/{generation_id}", response_model=GenerationOut)
def get_generation(
    generation_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    gen = db.query(Generation).filter(
        Generation.id == generation_id, Generation.user_id == current_user.id
    ).first()
    if not gen:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    return _to_out(gen)


@router.delete("/{generation_id}")
def delete_generation(
    generation_id: int,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    gen = db.query(Generation).filter(
        Generation.id == generation_id, Generation.user_id == current_user.id
    ).first()
    if not gen:
        raise HTTPException(status_code=404, detail="기록을 찾을 수 없습니다.")
    db.delete(gen)
    db.commit()
    return {"message": "삭제되었습니다."}
