# Lazy_AMPR headless web front end (for Unraid / any Docker host)
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    XDG_CONFIG_HOME=/config \
    HOME=/config \
    LAZY_AMPR_ROOTS=/games,/output \
    LAZY_AMPR_DEFAULT_OUTPUT=/output \
    LAZY_AMPR_PORT=8080 \
    PUID=99 \
    PGID=100 \
    UMASK=000

WORKDIR /app

COPY requirements-web.txt /app/
RUN pip install -r requirements-web.txt

COPY version.py /app/
COPY core /app/core
COPY utils /app/utils
COPY web /app/web
COPY resources /app/resources
COPY toml_profiles /app/toml_profiles
COPY external/ampr_emu/tools /app/external/ampr_emu/tools
COPY docker/entrypoint.sh /entrypoint.sh

RUN chmod 0755 /entrypoint.sh \
 && python -m compileall -q /app/core /app/utils /app/web /app/external/ampr_emu/tools \
 && mkdir -p /config /games /output

EXPOSE 8080
VOLUME ["/config"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"LAZY_AMPR_PORT\",\"8080\")}/healthz', timeout=4)" || exit 1

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "web"]
