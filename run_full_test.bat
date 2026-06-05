@echo off
cd /d "%~dp0"

echo [1/3] Cleaning old sessions...
for /d %%D in ("%USERPROFILE%\.kimi\sessions\P1_*") do rd /S /Q "%%D" 2>nul
for /d %%D in ("%USERPROFILE%\.kimi\sessions\P2_*") do rd /S /Q "%%D" 2>nul
for /d %%D in ("%USERPROFILE%\.kimi\sessions\P3_*") do rd /S /Q "%%D" 2>nul
for /d %%D in ("%USERPROFILE%\.kimi\sessions\P4_*") do rd /S /Q "%%D" 2>nul
for /d %%D in ("%USERPROFILE%\.kimi\sessions\P5_*") do rd /S /Q "%%D" 2>nul
for /d %%D in ("%USERPROFILE%\.kimi\sessions\P6_*") do rd /S /Q "%%D" 2>nul
for /d %%D in ("%USERPROFILE%\.kimi\sessions\P7_*") do rd /S /Q "%%D" 2>nul
for /d %%D in ("%USERPROFILE%\.kimi\sessions\NPC1_*") do rd /S /Q "%%D" 2>nul
echo   Done

echo [2/3] Starting full 7-day test...
set "PYTHON=C:\Users\27382\miniconda3\python.exe"
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8

(
echo @echo off
echo cd /d "%CD%"
echo set PYTHONUNBUFFERED=1
echo set PYTHONIOENCODING=utf-8
echo "%PYTHON%" -u scripts\test_orchestrator.py --python "%PYTHON%" --max-day 7 ^> shared\orchestrator_full.log 2^>^&1
) > shared\_run_test_temp.bat

start "" /MIN shared\_run_test_temp.bat

echo [3/3] Test is running in background
echo.
echo Log file: %CD%\shared\orchestrator_full.log
echo.
echo View last 50 lines:
echo   powershell -Command "Get-Content -Path '%CD%\shared\orchestrator_full.log' -Tail 50"
echo.
echo Live tail:
echo   powershell -Command "Get-Content -Path '%CD%\shared\orchestrator_full.log' -Tail 20 -Wait"
echo.
echo Stop test:
echo   taskkill /F /IM python.exe
echo.
pause
