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
COPY docs/index.html /app/docs/index.html

EXPOSE 8000
CMD ["uvicorn", "src.interfaces.tv_cockpit:app", "--host", "0.0.0.0", "--port", "8000"]
