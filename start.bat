@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Волна — новости

rem Ищем Python: сначала лаунчер py, потом python
set PY=
where py >nul 2>nul && set PY=py
if not defined PY (where python >nul 2>nul && set PY=python)
if not defined PY (
  echo Python не найден. Установите его с https://www.python.org/downloads/
  echo и отметьте галочку "Add python.exe to PATH".
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Первый запуск: создаю окружение и ставлю библиотеки, это займёт минуту...
  %PY% -m venv .venv || (pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt || (pause & exit /b 1)
)

".venv\Scripts\python.exe" run.py
pause
