@echo off
title R36Sync - Handheld Game Manager
echo Starting R36Sync...
py -3.12 main.py
if %ERRORLEVEL% NEQ 0 (
    echo Python 3.12 failed, trying default py launcher...
    py main.py
)
if %ERRORLEVEL% NEQ 0 (
    echo Failed to start. Please ensure Python 3.12+ is installed.
    pause
)
