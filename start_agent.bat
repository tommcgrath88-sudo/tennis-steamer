@echo off
title Tennis Steamer Agent
cd /d "c:\Users\tommc\my_ai_projects\Insurance"

:loop
echo [%date% %time%] Starting Tennis Steamer Agent...
call .venv\Scripts\python.exe main.py
echo [%date% %time%] Agent exited (code %errorlevel%). Restarting in 30 seconds...
timeout /t 30 /nobreak
goto loop
