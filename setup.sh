#!/usr/bin/env bash
# One-time setup on Mac/Linux WITHOUT Docker.   Run:  bash setup.sh
set -euo pipefail
echo "1/4 Creating virtual environment (.venv)..."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
echo "2/4 Installing packages (a few minutes)..."
.venv/bin/python -m pip install -r requirements.txt
echo "3/4 Building data/careers.db from data/raw (~1 min)..."
.venv/bin/python src/data_prep.py
echo "4/4 Building the course search index (one-off, 10-20 min)..."
.venv/bin/python src/course_search.py --build
[ -f .env ] || { cp .env.example .env; echo "Created .env - put your API key in it."; }
echo; echo "Done. Start the app with:"; echo "  source .venv/bin/activate && streamlit run src/app.py"
