"""Run once to initialize the database with admin user and default system prompt."""
import os
from dotenv import load_dotenv

load_dotenv()

from database import engine, SessionLocal
from models import Base, User, SystemPrompt
from auth import hash_password

DEFAULT_PROMPT = """당신은 CAD 형상 파라미터 추출 전문가입니다. 사용자의 자연어 또는 수치 입력을 파싱하여 순수한 JSON 객체만 반환하세요. 설명이나 다른 텍스트는 절대 포함하지 마세요.

지원하는 형상 타입:
- box: {"type": "box", "width": 숫자, "depth": 숫자, "height": 숫자}
- cylinder: {"type": "cylinder", "radius": 숫자, "height": 숫자}
- sphere: {"type": "sphere", "radius": 숫자}
- plate_with_holes: {"type": "plate_with_holes", "width": 숫자, "depth": 숫자, "height": 숫자, "holes": [{"radius": 숫자, "count": 정수}]}

결합 형상의 경우 두 번째 이후 형상에 "on_top": true를 추가하세요.

응답 형식: {"shapes": [...]}

예시:
입력: "100x50x10 박스" → {"shapes": [{"type": "box", "width": 100, "depth": 50, "height": 10}]}
입력: "지름 20 높이 50 원기둥" → {"shapes": [{"type": "cylinder", "radius": 10, "height": 50}]}
입력: "반지름 15 구" → {"shapes": [{"type": "sphere", "radius": 15}]}
입력: "가로 100 세로 50 두께 5 판에 지름 10 구멍 2개" → {"shapes": [{"type": "plate_with_holes", "width": 100, "depth": 50, "height": 5, "holes": [{"radius": 5, "count": 2}]}]}
입력: "60x60x20 박스 위에 반지름 10 높이 30 원기둥" → {"shapes": [{"type": "box", "width": 60, "depth": 60, "height": 20}, {"type": "cylinder", "radius": 10, "height": 30, "on_top": true}]}"""


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin_email = os.getenv("ADMIN_EMAIL", "admin@example.com")
        admin_pw = os.getenv("ADMIN_PASSWORD", "admin1234")

        if not db.query(User).filter(User.email == admin_email).first():
            db.add(User(
                email=admin_email,
                hashed_password=hash_password(admin_pw),
                is_approved=True,
                is_admin=True,
            ))
            print(f"[+] Admin created: {admin_email} / {admin_pw}")
        else:
            print(f"[=] Admin already exists: {admin_email}")

        if not db.query(SystemPrompt).filter(SystemPrompt.name == "main").first():
            db.add(SystemPrompt(name="main", content=DEFAULT_PROMPT))
            print("[+] Default system prompt created.")
        else:
            print("[=] System prompt already exists.")

        db.commit()
        print("[✓] Database initialization complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
