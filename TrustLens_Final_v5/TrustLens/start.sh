#!/bin/bash
cd "$(dirname "$0")/backend"
[ -d venv ] || python3 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt
echo; echo " TrustLens running -> open http://localhost:8000"; echo
uvicorn main:app --port 8000
