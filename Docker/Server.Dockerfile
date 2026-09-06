FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VERDICT_CONTAINER=1 \
    VERDICT_DATA_DIR=/data \
    VERDICT_STATIC_ROOT=/data/staticfiles \
    VERDICT_WATCHER_LOCK=/data/openbench_watchers.lock

WORKDIR /app

COPY requirements.txt /app/requirements.txt
COPY Docker/server-requirements.txt /app/Docker/server-requirements.txt
RUN pip install --no-cache-dir -r Docker/server-requirements.txt

RUN groupadd --gid 1000 verdict && \
    useradd --uid 1000 --gid verdict --no-create-home verdict && \
    mkdir /data && chown verdict:verdict /data

COPY OpenBench /app/OpenBench
COPY OpenSite /app/OpenSite
COPY Templates /app/Templates
COPY Config /app/Config
COPY Engines /app/Engines
COPY Books /app/Books
COPY manage.py LICENSE /app/
COPY Docker/run-server.sh Docker/healthcheck.py /app/Docker/

USER 1000:1000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "/app/Docker/healthcheck.py"]

ENTRYPOINT ["sh", "/app/Docker/run-server.sh"]
CMD ["gunicorn", "OpenSite.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "120", "--graceful-timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
