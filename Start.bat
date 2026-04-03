@echo off
cd /d "%~dp0"

set VENV_PY=.venv\Scripts\pythonw.exe
if not exist "%VENV_PY%" set VENV_PY=python

%VENV_PY% start.py
