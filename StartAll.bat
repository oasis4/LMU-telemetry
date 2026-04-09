@echo off
setlocal
cd /d "%~dp0"

echo ======================================
echo   LMU Telemetry - Launcher
echo ======================================
echo.
echo [1] Web Analyzer  (Browser UI - Backend + Frontend)
echo [2] Docker Start   (Web Analyzer via Docker Compose)
echo.
set /p CHOICE="Select [1/2]: "

if "%CHOICE%"=="1" goto WEB
if "%CHOICE%"=="2" goto DOCKER
echo Invalid choice.
pause
goto :eof

:WEB
echo.
echo Starting Web Analyzer...
echo   Backend:  http://localhost:8001
echo   Frontend: http://localhost:5173
echo.

set VENV_PY=.venv\Scripts\python.exe
set PY_CMD=python
if exist "%VENV_PY%" set PY_CMD=%VENV_PY%

rem Check if dependencies are installed
%PY_CMD% -c "import fastapi; import uvicorn" 2>nul
if errorlevel 1 (
    echo Installing Python dependencies...
    %PY_CMD% -m pip install -r requirements.txt
)

rem Start backend in background
echo Starting backend on port 8001...
start "LMU-Backend" %PY_CMD% -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload

rem Check if npm is available for frontend
where npm >nul 2>nul
if errorlevel 1 (
    echo.
    echo NOTE: npm not found. Install Node.js to run the frontend dev server.
    echo The backend API is running at http://localhost:8001
    echo.
    pause
    goto :eof
)

rem Start frontend dev server
echo Starting frontend dev server on port 5173...
cd frontend
if not exist node_modules (
    echo Installing frontend dependencies...
    call npm install
)
start "LMU-Frontend" cmd /c "npm run dev"
cd /d "%~dp0"

echo.
echo Both servers started! Open http://localhost:5173 in your browser.
echo Close terminal windows to stop.
pause
goto :eof

:DOCKER
echo.
echo Starting via Docker Compose...
docker compose up --build -d
if errorlevel 1 (
    echo.
    echo ERROR: Docker build failed. Make sure Docker Desktop is running.
    pause
    goto :eof
)
echo.
echo Services started!
echo   Frontend: http://localhost:3000
echo   Backend:  http://localhost:8001
echo.
echo Run "docker compose logs -f" to see logs.
echo Run "docker compose down" to stop.
pause
goto :eof
