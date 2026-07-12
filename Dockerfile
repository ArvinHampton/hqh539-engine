# HQH-539-512 Streamlit app — Render / local Docker
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    PORT=8080

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py billing.py config.py database.py hqh539.py crypto_hqh.py \
     deposit_store.py locate.py usage_tracker.py webhook_handler.py \
     golden_vectors.json ./
COPY .streamlit .streamlit

EXPOSE 8080

# Render injects PORT (often 10000). Bind 0.0.0.0 so the proxy can reach Streamlit.
CMD ["sh", "-c", "exec streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false"]
