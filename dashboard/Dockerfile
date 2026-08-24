FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt -q

COPY .streamlit/ ./.streamlit/
COPY src/ ./src/

# APP_UID must match the host user that owns ./data and ./params (see README).
ARG APP_UID=1000
RUN useradd --create-home --uid ${APP_UID} app
USER ${APP_UID}

EXPOSE 8501

HEALTHCHECK --interval=15s --timeout=3s --start-period=40s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=2).status == 200 else 1)"

CMD ["streamlit", "run", "src/app.py", \
    "--server.port=8501", \
    "--server.address=0.0.0.0", \
    "--server.headless=true"]
