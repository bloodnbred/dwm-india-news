@echo off
rem ===========================================================================
rem run_all.cmd -- plain-CMD entry point for the full pipeline rebuild.
rem
rem run_all.ps1 is the real script; this only wraps it. The wrapper exists
rem because PowerShell's execution policy blocks unsigned .ps1 files on a lot
rem of managed laptops, and a blocked script reads as a broken project rather
rem than a machine setting. -ExecutionPolicy Bypass is scoped to this one
rem process and changes nothing permanent.
rem
rem Arguments pass straight through, so the flags in run_all.ps1 still work:
rem     run_all.cmd -clean         also remove the warehouse first
rem     run_all.cmd -skipAnalysis  rebuild the warehouse, skip mining/report
rem
rem The exit code is the script's, because run_all.ps1 deliberately exits
rem non-zero when a stage fails and we must not paper over that. The pause at
rem the end is there for double-clicking; it keeps the failing stage on screen.
rem ===========================================================================

setlocal
cd /d "%~dp0"

where powershell >nul 2>nul
if errorlevel 1 (
    echo powershell.exe was not found on PATH.
    pause
    exit /b 1
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_all.ps1" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
    echo.
    echo run_all.ps1 exited %CODE%. The failing stage is named above.
)

pause
exit /b %CODE%