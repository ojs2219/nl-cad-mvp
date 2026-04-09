from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
from models import User, Generation, SystemPrompt
from schemas import UserOut, SystemPromptOut, SystemPromptUpdate
from auth import get_admin_user

router = APIRouter()


@router.get("/users", response_model=List[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    return db.query(User).order_by(User.created_at.desc()).all()


@router.put("/users/{user_id}/approve")
def approve_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.is_approved = True
    db.commit()
    return {"message": "승인되었습니다."}


@router.put("/users/{user_id}/revoke")
def revoke_user(user_id: int, db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    user.is_approved = False
    db.commit()
    return {"message": "승인이 취소되었습니다."}


@router.get("/prompt", response_model=SystemPromptOut)
def get_prompt(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    prompt = db.query(SystemPrompt).filter(SystemPrompt.name == "main").first()
    if not prompt:
        raise HTTPException(status_code=404, detail="시스템 프롬프트가 없습니다.")
    return prompt


@router.put("/prompt", response_model=SystemPromptOut)
def update_prompt(
    update: SystemPromptUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(get_admin_user),
):
    prompt = db.query(SystemPrompt).filter(SystemPrompt.name == "main").first()
    if not prompt:
        raise HTTPException(status_code=404, detail="시스템 프롬프트가 없습니다.")
    prompt.content = update.content
    db.commit()
    db.refresh(prompt)
    return prompt


@router.get("/generations")
def list_generations(db: Session = Depends(get_db), _: User = Depends(get_admin_user)):
    records = (
        db.query(Generation)
        .order_by(Generation.created_at.desc())
        .limit(200)
        .all()
    )
    return [
        {
            "id": g.id,
            "user_id": g.user_id,
            "user_email": g.user.email if g.user else None,
            "input_text": g.input_text,
            "status": g.status,
            "stl_url": g.stl_url,
            "created_at": g.created_at,
        }
        for g in records
    ]
