# DAGonService container image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=57000

WORKDIR /srv/dagonservice

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY dagonservice dagonservice
COPY wsgi.py .

RUN useradd --system --uid 10001 --home-dir /srv/dagonservice dagonservice
USER dagonservice

EXPOSE 57000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/check' % os.environ.get('PORT','57000'), timeout=4)"

# Threads, not processes: the service is I/O-bound on MongoDB, and one process
# keeps the optional webhook pool and logging simple.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT} --workers ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-8} --access-logfile - wsgi:app"]
