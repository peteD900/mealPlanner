#!/bin/bash
fuser -k 8000/tcp 2>/dev/null
pkill -f "main.py" 2>/dev/null
sleep 1
uv run python main.py
