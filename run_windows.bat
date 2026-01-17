@echo off
title Drone Hardware Scanner

echo Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python is not installed or not in your PATH.
    echo     Please install Python from python.org.
    pause
    exit
)

python launcher.py
