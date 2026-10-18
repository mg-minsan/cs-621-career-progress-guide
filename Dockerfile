# Career Progress Guide - one image with everything: code, database, search index, models.
#   docker compose up --build        (first build ~5 min; ~20 min more if data/index is not in git)
#   then open http://localhost:8501
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/app/.hf_cache \
    TOKENIZERS_PARALLELISM=false \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

WORKDIR /app

# 1. CPU-only PyTorch first (~200 MB instead of several GB of GPU libraries).
RUN pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu

# 2. Everything else (torch is already satisfied, so it is not downloaded again).
COPY requirements.txt .
RUN pip install -r requirements.txt

# 3. Build data/careers.db from the four raw SkillsFuture spreadsheets (~1 min).
#    data/index (the course search vectors) comes from git if it is there.
COPY data ./data
COPY src/data_prep.py ./src/
RUN python src/data_prep.py

# 4. Download the two search models. Build the course index only if it was not in git
#    (building it embeds 26k courses: 10-20 min, once).
COPY src/course_search.py ./src/
RUN if [ -f data/index/course_vectors.npy ]; then echo "Using the course index from git"; \
    else python src/course_search.py --build; fi \
 && python -c "import sys; sys.path.insert(0, 'src'); import course_search as c; c._st_encoder(); c._st_reranker()"

# 5. The rest of the project.
COPY . .

# Models are inside the image now: never go online for them at run time.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

# fileWatcherType=none: nobody edits code inside the container, and the watcher otherwise
# prints harmless "No module named 'torchvision'" errors while scanning transformers' image models.
CMD ["streamlit", "run", "src/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--server.fileWatcherType=none"]
