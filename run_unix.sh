#!/bin/bash
# Simple launcher for Mac/Linux
echo "Checking Python..."

if command -v python3 &>/dev/null; then
    python3 launcher.py
else
    echo "[!] Python 3 is not installed or not in PATH."
    exit 1
fi
