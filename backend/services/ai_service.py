import re
import os
import json
from typing import Optional

DEFAULT_SYSTEM_PROMPT = """당신은 CAD 형상 파라미터 추출 전문가입니다. 사용자의 자연어 또는 수치 입력을 파싱하여 순수한 JSON 객체만 반환하세요. 설명이나 다른 텍스트는 절대 포함하지 마세요.

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


async def parse_input(
    text: str,
    system_prompt: Optional[str] = None,
    user_prompt: Optional[str] = None,
) -> dict:
    """Parse natural language input into structured CAD parameters."""
    # Regex parser first (fast, reliable for standard patterns)
    result = _regex_parse(text)
    if result:
        return result

    # Fall back to Claude API
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError(
            "입력을 이해하지 못했습니다. 예시 형식으로 입력해 주세요.\n"
            "예: '100x50x10 박스'  |  '지름 20 높이 50 원기둥'  |  '반지름 15 구'\n"
            "'가로 100 세로 50 두께 5 판에 지름 10 구멍 2개'  |  '60x60x20 박스 위에 반지름 10 높이 30 원기둥'"
        )

    try:
        import anthropic

        combined = system_prompt or DEFAULT_SYSTEM_PROMPT
        if user_prompt:
            combined += f"\n\n사용자 추가 지침:\n{user_prompt}"

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            system=combined,
            messages=[{"role": "user", "content": text}],
        )
        response_text = message.content[0].text.strip()

        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not json_match:
            raise ValueError("AI 응답에서 JSON을 추출할 수 없습니다.")

        params = json.loads(json_match.group())
        _validate_params(params)
        return params

    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"입력 해석에 실패했습니다: {e}")
    except Exception as e:
        raise ValueError(f"AI 서비스 오류가 발생했습니다: {e}")


def _validate_params(params: dict) -> None:
    if "shapes" not in params or not params["shapes"]:
        raise ValueError("형상 정보를 찾을 수 없습니다.")
    valid_types = {"box", "cylinder", "sphere", "plate_with_holes"}
    for shape in params["shapes"]:
        if shape.get("type") not in valid_types:
            raise ValueError(f"지원하지 않는 형상 타입: {shape.get('type')}")


def _extract_number(text: str, keywords: list) -> Optional[float]:
    for kw in keywords:
        m = re.search(rf"{kw}\s*[：:=]?\s*(\d+(?:\.\d+)?)", text, re.IGNORECASE)
        if m:
            return float(m.group(1))
    return None


def _parse_single(text: str) -> Optional[dict]:
    # Box: "100x50x10 박스"
    m = re.search(r"(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)\s*[xX×]\s*(\d+(?:\.\d+)?)", text)
    if m and any(k in text for k in ["박스", "직육면체", "상자"]):
        return {"type": "box", "width": float(m.group(1)), "depth": float(m.group(2)), "height": float(m.group(3))}

    # Box with Korean keywords: "가로 100 세로 50 높이 10 박스"
    if any(k in text for k in ["박스", "직육면체", "상자"]):
        w = _extract_number(text, ["가로", "width"])
        d = _extract_number(text, ["세로", "depth"])
        h = _extract_number(text, ["높이", "height"])
        if w and d and h:
            return {"type": "box", "width": w, "depth": d, "height": h}

    # Cylinder: "지름 20 높이 50 원기둥"
    if any(k in text for k in ["원기둥", "실린더", "cylinder"]):
        h = _extract_number(text, ["높이", "height"])
        d = _extract_number(text, ["지름", "직경", "diameter"])
        r = _extract_number(text, ["반지름", "반경", "radius"])
        if h and (d or r):
            return {"type": "cylinder", "radius": r if r else d / 2, "height": h}

    # Sphere: "반지름 15 구"
    if "구" in text and "원기둥" not in text and "구멍" not in text:
        r = _extract_number(text, ["반지름", "반경", "radius"])
        d = _extract_number(text, ["지름", "직경", "diameter"])
        if r:
            return {"type": "sphere", "radius": r}
        if d:
            return {"type": "sphere", "radius": d / 2}

    # Plate with holes: "가로 100 세로 50 두께 5 판에 지름 10 구멍 2개"
    if ("판" in text or "plate" in text.lower()) and ("구멍" in text or "홀" in text or "hole" in text.lower()):
        w = _extract_number(text, ["가로", "width"])
        d = _extract_number(text, ["세로", "depth"])
        h = _extract_number(text, ["두께", "thickness", "높이", "height"])
        hole_d = _extract_number(text, ["지름", "직경", "diameter"])
        hole_r = _extract_number(text, ["반지름", "반경", "radius"])
        cm = re.search(r"구멍\s*(\d+)\s*개", text) or re.search(r"(\d+)\s*개?\s*구멍", text)
        count = int(cm.group(1)) if cm else 1
        if w and d and h:
            hr = hole_r if hole_r else (hole_d / 2 if hole_d else 5.0)
            return {
                "type": "plate_with_holes",
                "width": w,
                "depth": d,
                "height": h,
                "holes": [{"radius": hr, "count": count}],
            }

    return None


def _regex_parse(text: str) -> Optional[dict]:
    text = text.strip()

    if "위에" in text:
        idx = text.index("위에")
        base = _parse_single(text[:idx].strip())
        top = _parse_single(text[idx + 2:].strip())
        if base and top:
            top["on_top"] = True
            return {"shapes": [base, top]}

    shape = _parse_single(text)
    return {"shapes": [shape]} if shape else None
