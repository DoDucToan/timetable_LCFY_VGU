@echo off
REM Create virtual environment if it doesn't exist
if not exist .venv (
    python -m venv .venv
)

REM Activate virtual environment
call .venv\Scripts\activate

REM Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

REM Run the FastAPI app
python -m uvicorn app.main:app --reload
