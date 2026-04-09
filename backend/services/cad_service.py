import subprocess
import os
import sys
import shutil


def get_openscad_path() -> str:
    path = os.getenv("OPENSCAD_PATH", "").strip()
    if path:
        return path

    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\OpenSCAD\openscad.exe",
            r"C:\Program Files\OpenSCAD\openscad.com",
            r"C:\Program Files (x86)\OpenSCAD\openscad.exe",
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    elif sys.platform == "darwin":
        mac_path = "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"
        if os.path.exists(mac_path):
            return mac_path

    return "openscad"  # assume it's in PATH


def _build_cmd(openscad: str, stl_path: str, scad_path: str) -> list:
    """Build the OpenSCAD command, wrapping with xvfb-run on Linux if available."""
    cmd = [openscad, "-o", stl_path, scad_path]
    # On Linux without DISPLAY set, use xvfb-run for headless rendering
    if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
        xvfb = shutil.which("xvfb-run")
        if xvfb:
            cmd = [xvfb, "-a", "--server-args=-screen 0 1280x1024x24"] + cmd
    return cmd


def generate_stl(scad_code: str, scad_path: str, stl_path: str) -> None:
    """Write OpenSCAD code to file and run OpenSCAD to produce STL."""
    os.makedirs(os.path.dirname(os.path.abspath(scad_path)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(stl_path)), exist_ok=True)

    with open(scad_path, "w", encoding="utf-8") as f:
        f.write(scad_code)

    openscad = get_openscad_path()
    cmd = _build_cmd(openscad, stl_path, scad_path)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            stderr = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(f"OpenSCAD 변환 실패:\n{stderr}")

        if not os.path.exists(stl_path) or os.path.getsize(stl_path) == 0:
            raise RuntimeError("STL 파일이 생성되지 않았습니다.")

    except subprocess.TimeoutExpired:
        raise RuntimeError("STL 변환 시간이 초과되었습니다 (60초).")
    except FileNotFoundError:
        raise RuntimeError(
            "OpenSCAD 실행 파일을 찾을 수 없습니다.\n"
            "OpenSCAD를 설치하거나 .env의 OPENSCAD_PATH를 설정해 주세요.\n"
            "다운로드: https://openscad.org/downloads.html"
        )
