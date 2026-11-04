FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mynews mynews
COPY static static
COPY run.py .
ENV MYNEWS_HOST=0.0.0.0 MYNEWS_DB_PATH=/app/data/news.db
VOLUME /app/data
EXPOSE 8000
CMD ["python", "run.py"]
