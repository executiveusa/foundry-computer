FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .
COPY src src
COPY web web
ENV FOUNDRY_DATABASE_PATH=/data/foundry.db
VOLUME /data
EXPOSE 8000
CMD ["uvicorn","foundry.main:app","--host","0.0.0.0","--port","8000","--app-dir","src"]
