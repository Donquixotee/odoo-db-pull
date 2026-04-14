FROM python:3.11-slim

# System deps: rsync + openssh-client (for rsync over SSH) + postgresql-client (pg_restore/createdb)
RUN apt-get update && apt-get install -y --no-install-recommends \
    rsync \
    openssh-client \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8100

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8100"]