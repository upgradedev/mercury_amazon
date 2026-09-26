FROM python:3.11-slim as builder
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip setuptools build
COPY src/ src/
RUN pip wheel --no-deps -w /app/dist .

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app/dist/*.whl /app/
RUN pip install --no-cache-dir /app/*.whl fastapi uvicorn
# The server resolves the cockpit page as ../../../docs relative to its own file,
# so the package is present under /app as well as in site-packages and the page
# is copied beside it. The import below is the one tests/unit/test_container_entrypoint.py
# performs, so a renamed module fails the suite before it fails the container.
COPY src/ /app/src/
COPY docs/index.html /app/docs/index.html
# The page's scripts, manifest and self-hosted fonts, which it loads relatively
# from the same origin. The licences for the fonts travel with them.
COPY docs/firetv_nav.js docs/webmcp_bridge.js docs/manifest.json /app/docs/
COPY docs/*.woff2 docs/OFL-*.txt /app/docs/

EXPOSE 8002
CMD ["uvicorn", "src.interfaces.mcp_server:app", "--host", "0.0.0.0", "--port", "8002"]
