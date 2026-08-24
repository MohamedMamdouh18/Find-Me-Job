FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt -q

COPY alembic.ini .
COPY src/ ./src/
COPY tests/ ./tests/

# Drop root; /data is bind-mounted from the host and stays owned by the host user.
# APP_UID must match the host user that owns ./data and ./params (see README).
ARG APP_UID=1000
RUN useradd --create-home --uid ${APP_UID} app
USER ${APP_UID}

EXPOSE 8001

HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=2).status == 200 else 1)"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
