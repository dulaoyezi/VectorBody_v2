FROM python:3.10-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY requirements_web.txt .
RUN pip install --no-cache-dir -r requirements_web.txt
COPY core ./core
COPY web ./web
COPY web_app.py .
ENV VECTORBODY_DATA_DIR=/app/web_data PORT=8000 PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn web_app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]