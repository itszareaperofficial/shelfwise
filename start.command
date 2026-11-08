#!/bin/sh
cd "$(dirname "$0")"
command -v python3 >/dev/null || { echo "Install Python 3 from https://www.python.org/downloads/ and run this again."; exit 1; }
(sleep 2; open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null) &
echo "Shelfwise is running at http://localhost:8000 (close this window to stop it)"
python3 server.py
