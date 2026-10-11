FROM python:3.14-slim
WORKDIR /app
COPY monitor.py watchlist.json ./
RUN useradd --uid 10001 --create-home monitor && mkdir /app/data && chown monitor:monitor /app/data
USER monitor
ENV PYTHONUNBUFFERED=1
CMD ["python", "monitor.py", "run"]
