# TRUSTLENS - setup (Windows)

1. Install Python 3.12 from https://www.python.org/downloads/ (tick "Add Python to PATH").
   Newer Python versions can fail to install some packages; 3.12 is the safe choice.
2. (Optional, for AI) Free key from https://aistudio.google.com .
   In the backend folder, copy ".env.example" to a new file named ".env" and write:
   GEMINI_API_KEY=your-key
   (In Notepad: Save as -> "All files" -> name it .env). No key = rules-only mode, still works.
3. Double-click start.bat. First run takes 1-3 minutes. Keep the window open.
4. The browser opens http://localhost:8000 (open it yourself if not).

Mac/Linux: run `bash start.sh` instead of start.bat.

## Quick test
Click the "Misleading" sample -> Analyze (low rating, red). Click "Credible" -> Analyze (high rating, green).
Top-right label shows "AI: gemini" or "AI off (rules only)". "Backend offline" = start window closed.

## Problems
- "Python was not found": reinstall Python with "Add Python to PATH".
- Install fails: delete backend\venv, check internet, run start.bat again.
- AI error 404/403: wrong key or model; set GEMINI_MODEL in .env (see AI Studio).
- Rate limit note: wait a minute; rules-only results still appear.
- Reset history: delete backend\trustlens.db.

## Files
backend/main.py (API) | frontend/index.html (UI) | frontend/config.js (API address)
render.yaml (optional free hosting on Render) | ARCHITECTURE.md (system design for your viva)

## Put it online (free, one link) - Render
1. Make a GitHub repo and upload this folder (do NOT upload backend\venv, backend\.env or *.db).
2. On render.com sign in with GitHub -> New -> Blueprint -> pick the repo -> Apply. Paste GEMINI_API_KEY when asked.
3. After the build (3-6 min) open the https://...onrender.com link and share it.
Free plan sleeps after ~15 min idle (first load ~1 min) and history resets on restart.
