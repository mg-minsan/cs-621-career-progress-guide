# One-time setup on Windows WITHOUT Docker.
# Run from the project folder:   powershell -ExecutionPolicy Bypass -File setup.ps1
$ErrorActionPreference = "Stop"

Write-Host "1/4 Creating virtual environment (.venv)..." -ForegroundColor Cyan
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip

Write-Host "2/4 Installing packages (a few minutes)..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Write-Host "3/4 Building data\careers.db from data\raw (~1 min)..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe src\data_prep.py

Write-Host "4/4 Building the course search index (one-off, 10-20 min)..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe src\course_search.py --build

if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env - put your API key in it." -ForegroundColor Yellow }

Write-Host "`nDone. Next time, start the app with:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host "  streamlit run src/app.py"
