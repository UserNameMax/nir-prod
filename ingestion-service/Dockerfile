FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y unar && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DATA_SERVICE_URL=http://data-service:8000

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001", "--h11-max-incomplete-event-size", "10485760"]
