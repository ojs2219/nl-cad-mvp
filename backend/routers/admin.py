from fastapi import APIRouter, Depends, HTTPException
from typing import List
from schemas import UserOut, SystemPromptOut, SystemPromptUpdate
from auth import get_admin_user
import db_ops

router = APIRouter()


@router.get("/users", response_model=List[UserOut])
def list_users(_=Depends(get_admin_user)):
    return db_ops.get_all_users()


@router.put("/users/{user_id}/approve")
def approve_user(user_id: int, _=Depends(get_admin_user)):
    if not db_ops.set_user_approved(user_id, True):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return {"message": "승인되었습니다."}


@router.put("/users/{user_id}/revoke")
def revoke_user(user_id: int, _=Depends(get_admin_user)):
    if not db_ops.set_user_approved(user_id, False):
        raise HTTPException(status_code=404, detail="사용자를 찾을 수 없습니다.")
    return {"message": "승인이 취소되었습니다."}


@router.get("/prompt", response_model=SystemPromptOut)
def get_prompt(_=Depends(get_admin_user)):
    prompt = db_ops.get_system_prompt()
    if not prompt:
        raise HTTPException(status_code=404, detail="시스템 프롬프트가 없습니다.")
    return prompt


@router.put("/prompt", response_model=SystemPromptOut)
def update_prompt(update: SystemPromptUpdate, _=Depends(get_admin_user)):
    prompt = db_ops.set_system_prompt(update.content)
    if not prompt:
        raise HTTPException(status_code=404, detail="시스템 프롬프트가 없습니다.")
    return prompt


@router.get("/generations")
def list_generations(_=Depends(get_admin_user)):
    gens = db_ops.get_all_generations(limit=200)
    return [
        {
            "id": g.id,
            "user_id": g.user_id,
            "user_email": g.user_email,
            "input_text": g.input_text,
            "status": g.status,
            "stl_url": g.stl_url,
            "created_at": g.created_at,
        }
        for g in gens
    ]
