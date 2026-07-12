# HQH-539 Streamlit app — Render / local Docker
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py billing.py config.py database.py hqh539.py \
     locate.py usage_tracker.py webhook_handler.py \
     golden_vectors.json ./

EXPOSE 8080

# Render injects PORT; default 8080 for local `docker run -p 8080:8080`
CMD ["sh", "-c", "streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true"]
