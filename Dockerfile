FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY herve ./herve
RUN useradd --create-home herve && mkdir -p /app/data && chown herve /app/data
USER herve

# Port d'écoute des événements de la centrale Ajax (SIA DC-09)
EXPOSE 12128
CMD ["python", "-m", "herve", "/app/config.yaml"]
