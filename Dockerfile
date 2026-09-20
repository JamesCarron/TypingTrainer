# TypingTrainer web UI, built on the box (see infra/apps/typingtrainer/compose.yml).
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir platformdirs
COPY src/ ./src/
COPY scripts/serve.py ./scripts/serve.py
ENV PYTHONPATH=/app/src \
    TYPINGTRAINER_HOME=/data \
    TYPINGTRAINER_NO_BROWSER=1
VOLUME /data
EXPOSE 8000
CMD ["python", "scripts/serve.py", "--host", "0.0.0.0", "--port", "8000", "--no-browser"]
