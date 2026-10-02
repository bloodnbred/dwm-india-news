@echo off
rem ===========================================================================
rem open-dashboard.cmd -- start the dashboard and open the browser.
rem
rem One command for a demonstration: double-click this file.
rem
rem WHY IT WAITS. `dwm serve` copies the warehouse into a snapshot before
rem uvicorn starts listening, because DuckDB locks its file exclusively and the
rem CLI has to stay usable during a demo. The port is therefore busy for a
rem moment before the dashboard is real. Opening a browser on "the port is
rem up" alone gets a blank page or a connection error, so we poll /health and
rem open only once the server answers -- with a 30 second ceiling, after which
rem we say so rather than sitting there forever.
rem
rem WHY THE WINDOW STAYS OPEN. This is deliberate, not a bug. This window owns
rem the server process, and closing it is how you stop the server. A launcher
rem that vanished on success would hide the one control that matters.
rem
rem WHY IT TOLERATES A SECOND RUN. If a healthy server is already up we skip
rem straight to the browser instead of dying on the port clash, so running it
rem twice by accident is harmless.
rem
rem On failure we pause with the Python output left on screen. A window that
rem closes on its own and takes the traceback with it is the worst outcome,
rem because the missing text is exactly what you need to read.
rem ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "HOST=127.0.0.1"
set "PORT=8000"
set "URL=http://%HOST%:%PORT%"
set "PY=.\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo Could not find %PY%
    echo Run this from the repo root, or create the virtualenv first.
    pause
    exit /b 1
)

call :is_ready
if "%READY%"=="1" (
    echo Server already running at %URL% -- skipping startup.
    call :report_body
    start "" "%URL%"
    exit /b 0
)

echo Starting the dashboard. First run copies a warehouse snapshot, so this
echo takes a moment.
start "dwm serve" /b "%PY%" -m dwm serve

set /a WAITED=0

:wait
call :is_ready
if "!READY!"=="1" goto ready
if !WAITED! geq 30 goto timeout
ping -n 2 127.0.0.1 >nul
set /a WAITED+=2
goto wait

:ready
echo.
echo Dashboard is up after ~!WAITED!s.
call :report_body
start "" "%URL%"
echo.
echo Leave this window open. Closing it stops the server.
goto done

:timeout
echo.
echo WARNING: no answer from %URL%/health after 30 seconds.
echo The Python output above is the reason. Read it before closing this
echo window -- the usual cause is a missing warehouse, fixed by run_all.cmd.
goto done

:done
pause
exit /b 0


rem ---------------------------------------------------------------------------
rem is_ready -- 1 when /health answers, 0 otherwise. Sets BODY to what it said.
rem
rem curl.exe ships with Windows 10 1803 and later, so this stays plain CMD and
rem needs no PowerShell execution policy of its own.
rem ---------------------------------------------------------------------------
:is_ready
set "READY=0"
set "BODY="
for /f "usebackq delims=" %%b in (`curl.exe -s -m 2 "%URL%/health" 2^>nul`) do set "BODY=%%b"
if defined BODY echo !BODY!| findstr /c:"status" >nul && set "READY=1"
exit /b 0


rem ---------------------------------------------------------------------------
rem report_body -- say so when the server is up but has no results.
rem
rem /health answers 200 even with nothing behind it, by design: its docstring in
rem dwm/api/app.py argues that a bare {"ok": true} would be true on a server
rem with no warehouse, which is when a client most needs telling. So a reachable
rem server is NOT the same as a server holding findings, and a poll that only
rem looked at the status code would miss that entirely.
rem
rem We still open the browser. A demo that starts with a visible warning beats
rem a demo that refuses to start, and hiding the problem behind a bare dashboard
rem would imply it had data. Drop the quotes before matching so the search does
rem not have to escape any.
rem ---------------------------------------------------------------------------
:report_body
set "NOBODY=!BODY:"=!"
echo !NOBODY!| findstr /c:"facts:false" >nul
if not errorlevel 1 (
    echo WARNING: the server is up but has no results loaded ^^(facts=false^).
    echo          The dashboard will open, but it may show no findings.
    echo          On a fresh clone, run run_all.cmd first.
)
exit /b 0