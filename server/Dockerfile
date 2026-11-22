FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
ENV PORT=8000 HOST=0.0.0.0 SYNORA_DB=/app/data/synora.db
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["python", "server.py"]
