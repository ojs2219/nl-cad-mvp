# NL-CAD MVP

자연어 또는 수치 입력으로 3D CAD 형상(STL)을 생성하는 테스트용 웹 애플리케이션.

**스택:** React + Vite (Vercel) · FastAPI + **Supabase** PostgreSQL/Storage (Render/Docker) · Three.js · OpenSCAD

---

## 로컬 개발

### 사전 요구사항

- Python 3.9+
- Node.js 18+
- [OpenSCAD](https://openscad.org/downloads.html) 설치

### 실행

```bash
# 터미널 1 — 백엔드
start-backend.bat          # Windows
# 또는 수동:
cd backend
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements.txt
python init_db.py
uvicorn main:app --reload --port 8000

# 터미널 2 — 프론트엔드
start-frontend.bat         # Windows
# 또는 수동:
cd frontend
npm install
npm run dev
```

- 프론트엔드: http://localhost:5173
- 백엔드 API: http://localhost:8000
- API 문서: http://localhost:8000/docs

기본 관리자 계정: `admin@example.com` / `admin1234`  
(`backend/.env`에서 변경 가능)

---

## Supabase CLI 연결

### 설치 (Windows)

```powershell
# 방법 1 — Scoop (권장)
scoop bucket add supabase https://github.com/supabase/scoop-bucket.git
scoop install supabase

# 방법 2 — npm
npm install -g supabase

# 방법 3 — winget
winget install Supabase.CLI
```

설치 확인:
```bash
supabase --version
```

### 프로젝트 연결

```bash
# 1. 로그인 (브라우저 열림)
supabase login

# 2. 로컬 초기화 (프로젝트 루트에서)
cd C:\Users\user\cad-mvp
supabase init

# 3. Supabase 프로젝트와 연결
#    Project ref: 대시보드 URL의 https://supabase.com/dashboard/project/<ref>
supabase link --project-ref <YOUR_PROJECT_REF>

# 4. 환경변수 확인
supabase status
```

### Supabase 프로젝트 설정

**대시보드에서 해야 할 일:**

1. [supabase.com](https://supabase.com) → New Project 생성
2. **Storage** → **New Bucket** → 이름: `stl-files`, Public: ON
3. **Project Settings → API** 에서 값 복사:
   - `Project URL` → `SUPABASE_URL`
   - `service_role` 키 → `SUPABASE_SERVICE_KEY` (절대 프론트엔드에 노출 금지)
4. **Project Settings → Database → Connection string (URI)** → `DATABASE_URL`

### .env 업데이트

```bash
# backend/.env
SUPABASE_URL=https://xxxxxxxxxxxx.supabase.co
SUPABASE_SERVICE_KEY=eyJhbGciOiJIUzI1...
DATABASE_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres
```

### 테이블 생성 (첫 실행 시 자동)

SQLAlchemy가 `init_db.py` 실행 시 테이블을 자동 생성합니다.  
Supabase CLI 마이그레이션 없이 바로 사용 가능합니다.

```bash
cd backend
python init_db.py   # 또는 start-backend.bat 실행 시 자동 실행
```

---

## 배포: Render (백엔드) + Vercel (프론트엔드)

### 개요

```
사용자 브라우저
    │  HTTPS
    ▼
Vercel (React SPA)
    │  HTTPS + CORS
    ▼
Render (FastAPI + Docker + OpenSCAD)    ←── Supabase PostgreSQL (DB)
    │  STL 업로드                        ←── Supabase Storage (STL CDN)
    ▼
Supabase Storage CDN (STL 직접 서빙)
    │
    ▼
사용자 브라우저 (Three.js STL 로드)
```

---

## Step 1 — GitHub에 코드 올리기

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/nl-cad.git
git push -u origin main
```

---

## Step 2 — Render에 백엔드 배포

### 2-1. Render 계정 및 서비스 생성

1. [render.com](https://render.com) → **New → Web Service**
2. GitHub 저장소 연결
3. 설정:

| 항목 | 값 |
|---|---|
| **Environment** | `Docker` |
| **Root Directory** | `backend` |
| **Dockerfile Path** | `./Dockerfile` |
| **Plan** | Starter ($7/월) 권장 · Free 가능 (주의사항 아래 참고) |

### 2-2. 환경변수 설정 (Render Dashboard → Environment)

| 변수 | 값 | 설명 |
|---|---|---|
| `SECRET_KEY` | (Generate) | Render에서 자동 생성 |
| `ADMIN_EMAIL` | `admin@example.com` | 초기 관리자 이메일 |
| `ADMIN_PASSWORD` | (강력한 비밀번호) | 초기 관리자 비밀번호 |
| `SUPABASE_URL` | `https://xxx.supabase.co` | Supabase Project URL |
| `SUPABASE_SERVICE_KEY` | `eyJ...` | Supabase service_role 키 |
| `DATABASE_URL` | `postgresql://postgres:...` | Supabase DB 연결 문자열 |
| `CORS_ORIGINS` | `https://YOUR-APP.vercel.app` | Vercel 배포 후 URL로 업데이트 |
| `CORS_ORIGIN_REGEX` | `https://.*\.vercel\.app` | Vercel 프리뷰 URL 허용 |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | (선택) 없으면 정규식 파서만 사용 |

### 2-3. Persistent Disk 불필요

Supabase PostgreSQL + Supabase Storage를 사용하므로 Render Persistent Disk가 필요 없습니다.  
**Free 플랜**으로 배포 가능합니다. (15분 비활성 시 슬립, 첫 요청 ~30초 콜드 스타트)

### 2-4. 배포 확인

```bash
curl https://YOUR-BACKEND.onrender.com/api/health
# → {"status":"ok"}
```

---

## Step 3 — Vercel에 프론트엔드 배포

### 3-1. Vercel 계정 및 프로젝트 생성

1. [vercel.com](https://vercel.com) → **New Project**
2. GitHub 저장소 연결
3. 설정:

| 항목 | 값 |
|---|---|
| **Framework Preset** | `Vite` |
| **Root Directory** | `frontend` |
| **Build Command** | `npm run build` (자동) |
| **Output Directory** | `dist` (자동) |

### 3-2. 환경변수 설정 (Vercel Dashboard → Settings → Environment Variables)

| 변수 | 값 |
|---|---|
| `VITE_API_URL` | `https://YOUR-BACKEND.onrender.com` |

> `VITE_`로 시작하는 환경변수만 Vite 빌드에 포함됩니다.

### 3-3. 배포

설정 후 **Deploy** 클릭. 완료 후 Vercel이 URL을 제공합니다.  
예: `https://nl-cad.vercel.app`

### 3-4. Render CORS 업데이트

Vercel URL을 확인한 뒤 Render 환경변수 업데이트:

```
CORS_ORIGINS=https://nl-cad.vercel.app
```

Render 서비스가 자동으로 재배포됩니다.

---

## Step 4 — render.yaml로 자동 배포 (선택)

프로젝트 루트의 `render.yaml`을 사용하면 Render Blueprint로 한 번에 배포할 수 있습니다.

1. Render Dashboard → **New → Blueprint**
2. GitHub 저장소 선택
3. `render.yaml` 자동 감지 → 환경변수 입력 → Deploy

---

## 로컬 Docker 테스트

```bash
cd backend

# 빌드
docker build -t nl-cad-backend .

# 실행
docker run -p 8000:8000 \
  -e SECRET_KEY=dev-secret \
  -e ADMIN_EMAIL=admin@example.com \
  -e ADMIN_PASSWORD=admin1234 \
  -e CORS_ORIGINS=http://localhost:5173 \
  nl-cad-backend
```

---

## 환경변수 전체 목록

### 백엔드 (`backend/.env`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `SECRET_KEY` | `dev-secret-...` | JWT 서명 키 (프로덕션 필수 변경) |
| `DATABASE_URL` | `sqlite:///./cad_mvp.db` | DB 연결 문자열 |
| `STATIC_DIR` | `static` | STL/SCAD 파일 저장 경로 |
| `ANTHROPIC_API_KEY` | (없음) | Claude API 키 (선택) |
| `OPENSCAD_PATH` | (자동감지) | OpenSCAD 실행파일 경로 |
| `CORS_ORIGINS` | `http://localhost:5173` | 허용할 오리진 (콤마 구분) |
| `CORS_ORIGIN_REGEX` | `https://.*\.vercel\.app` | 허용할 오리진 정규식 |
| `ADMIN_EMAIL` | `admin@example.com` | 초기 관리자 이메일 |
| `ADMIN_PASSWORD` | `admin1234` | 초기 관리자 비밀번호 |

### 프론트엔드 (`frontend/.env.local`)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `VITE_API_URL` | `""` (빈 문자열) | 백엔드 URL (로컬: 비워두면 Vite 프록시 사용) |

---

## 지원 형상 (예시 입력)

```
100x50x10 박스
지름 20 높이 50 원기둥
반지름 15 구
가로 100 세로 50 두께 5 판에 지름 10 구멍 2개
60x60x20 박스 위에 반지름 10 높이 30 원기둥
```

---

## 아키텍처

```
frontend/          React + Vite + Three.js
  └─ src/
     ├─ pages/     Generator · History · Admin · Login · Register
     ├─ components/ Navbar · Preview3D · ProtectedRoute
     └─ api/       Axios client (VITE_API_URL 기반)

backend/           FastAPI
  ├─ routers/      auth · generate · history · admin
  ├─ services/
  │   ├─ ai_service.py      정규식 파서 + Claude API 폴백
  │   ├─ scad_generator.py  파라미터 → OpenSCAD 코드
  │   └─ cad_service.py     OpenSCAD CLI → STL
  ├─ Dockerfile    Ubuntu 22.04 + OpenSCAD + Xvfb
  └─ start.sh      Xvfb 시작 → DB 초기화 → uvicorn 실행
```
