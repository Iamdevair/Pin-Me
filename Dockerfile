FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pinme ./pinme
COPY config ./config

# Render, Railway, and Fly inject PORT. Default matches a local `python -m pinme`.
ENV PORT=8080
EXPOSE 8080

CMD ["python", "-m", "pinme"]
