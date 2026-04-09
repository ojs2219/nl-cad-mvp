from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import User
from schemas import UserRegister, UserLogin, Token, UserOut, UserSettingsUpdate
from auth import hash_password, verify_password, create_access_token, get_current_user, get_approved_user

router = APIRouter()


@router.post("/register", response_model=UserOut)
def register(user_data: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == user_data.email).first():
        raise HTTPException(status_code=400, detail="이미 등록된 이메일입니다.")
    if len(user_data.password) < 6:
        raise HTTPException(status_code=400, detail="비밀번호는 6자 이상이어야 합니다.")
    user = User(
        email=user_data.email,
        hashed_password=hash_password(user_data.password),
        is_approved=False,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(user_data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    if not user.is_approved and not user.is_admin:
        raise HTTPException(status_code=403, detail="관리자 승인 대기 중입니다. 승인 후 로그인할 수 있습니다.")
    token = create_access_token({"sub": str(user.id)})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/settings", response_model=UserOut)
def update_settings(
    settings: UserSettingsUpdate,
    current_user: User = Depends(get_approved_user),
    db: Session = Depends(get_db),
):
    current_user.custom_prompt = settings.custom_prompt
    db.commit()
    db.refresh(current_user)
    return current_user
