@echo off
setlocal
title TypingTrainer

REM ===========================================================================
REM  TypingTrainer - launcher
REM
REM  With no argument it serves the web UI on an EPHEMERAL port (the OS picks a
REM  free one) and opens the browser at its own address once it is listening.
REM  No port to configure and two copies can run at once without colliding.
REM
REM    TypingTrainer.bat              the web UI
REM    TypingTrainer.bat --desktop    the tkinter desktop app
REM
REM  Everything runs locally on 127.0.0.1; the tool makes no network calls.
REM ===========================================================================

cd /d "%~dp0"

if not exist "pixi.toml" (
    echo.
    echo   ERROR: cannot find "%~dp0pixi.toml"
    echo   This .bat must stay in the TypingTrainer folder.
    echo.
    pause
    exit /b 1
)

REM ---- locate pixi -----------------------------------------------------------
set "PIXI="
for /f "delims=" %%P in ('where pixi 2^>nul') do if not defined PIXI set "PIXI=%%P"
if not defined PIXI if exist "%USERPROFILE%\.pixi\bin\pixi.exe" set "PIXI=%USERPROFILE%\.pixi\bin\pixi.exe"
if not defined PIXI (
    echo.
    echo   ERROR: pixi was not found on PATH or in %%USERPROFILE%%\.pixi\bin.
    echo   Install it from https://pixi.sh, then run this again.
    echo.
    pause
    exit /b 1
)

REM pixi run installs the environment on first use; there is no separate install step.
if /i "%~1"=="--desktop" (
    "%PIXI%" run desktop
) else (
    "%PIXI%" run ui
)
echo.
echo   Stopped.
pause
