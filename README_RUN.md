# ChatBot_V11 (FastAPI + React web)

## Backend (FastAPI)

From the project root (the folder that contains `app/`):

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

Open API health:
- http://127.0.0.1:8000/

## Frontend (React + Vite)

In a second terminal:

```powershell
cd frontend-web
npm install
npm run dev
```

Open:
- http://localhost:5173/

The Vite dev server proxies API calls (e.g. `/buyer/chat`) to the backend on port 8000.

## Notes
- Do **not** run `uvicorn ...` directly on Windows. Use `python -m uvicorn ...` to avoid launcher path issues.
- If you see `ModuleNotFoundError: No module named 'app'`, you started the backend from the wrong folder. `cd` to the project root (where `app/` exists).
