@echo off
setlocal

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "BACKEND_DIR=%ROOT%\backend"
set "FRONTEND_DIR=%ROOT%\frontend"
set "BACKEND_PY=%BACKEND_DIR%\.venv\Scripts\python.exe"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"
set "FRONTEND_URL=http://localhost:%FRONTEND_PORT%"

echo.
echo DevLoopAI development launcher
echo Repository: "%ROOT%"
echo.

if not exist "%BACKEND_DIR%" (
  echo ERROR: backend folder was not found: "%BACKEND_DIR%"
  goto :error
)

if not exist "%FRONTEND_DIR%" (
  echo ERROR: frontend folder was not found: "%FRONTEND_DIR%"
  goto :error
)

if not exist "%BACKEND_PY%" (
  echo ERROR: backend virtual environment Python was not found:
  echo "%BACKEND_PY%"
  echo.
  echo Create/sync the backend virtual environment before using this launcher.
  goto :error
)

if not exist "%BACKEND_DIR%\app\main.py" (
  echo ERROR: FastAPI entrypoint was not found: "%BACKEND_DIR%\app\main.py"
  goto :error
)

if not exist "%FRONTEND_DIR%\package.json" (
  echo ERROR: frontend package.json was not found: "%FRONTEND_DIR%\package.json"
  goto :error
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found on PATH. Install Node.js or open a terminal where npm is available.
  goto :error
)

if /I "%~1"=="--check" (
  echo Check passed: required DevLoopAI files and npm are available.
  exit /b 0
)

call :is_port_listening %BACKEND_PORT%
if errorlevel 1 (
  echo Starting FastAPI backend on port %BACKEND_PORT%...
  start "DevLoopAI Backend" /D "%BACKEND_DIR%" cmd /k ""%BACKEND_PY%" -m uvicorn app.main:app --reload"
) else (
  echo Port %BACKEND_PORT% is already in use. Backend was not started again.
)

call :is_port_listening %FRONTEND_PORT%
if errorlevel 1 (
  echo Starting Next.js frontend on port %FRONTEND_PORT%...
  start "DevLoopAI Frontend" /D "%FRONTEND_DIR%" cmd /k "npm run dev"
) else (
  echo Port %FRONTEND_PORT% is already in use. Frontend was not started again.
)

echo.
echo Waiting briefly for startup...
timeout /t 6 /nobreak >nul

echo Opening %FRONTEND_URL%
start "" "%FRONTEND_URL%"
echo.
echo DevLoopAI launch requested. Keep the backend/frontend windows open while developing.
exit /b 0

:is_port_listening
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %1 -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>nul
exit /b %errorlevel%

:error
echo.
echo DevLoopAI was not started.
pause
exit /b 1
