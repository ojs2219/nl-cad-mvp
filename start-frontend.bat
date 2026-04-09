@echo off
cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo Installing npm dependencies...
    npm install
)

echo Starting React frontend on http://localhost:5173
npm run dev
