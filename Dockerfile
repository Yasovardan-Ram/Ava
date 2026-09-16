FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY app ./app
COPY main.py .
COPY ava_runtime_test.py ava_load_test.py ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir flask numpy openai pythermalcomfort python-dotenv scipy gunicorn

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["gunicorn", "-w", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "-b", "0.0.0.0:8000", "main:app"]
