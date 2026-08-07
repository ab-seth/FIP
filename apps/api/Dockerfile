FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system fip && adduser --system --ingroup fip fip

COPY pyproject.toml README.md ./
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN pip install --no-cache-dir .

USER fip

EXPOSE 8000

CMD ["uvicorn", "fip_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
