FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt ./
RUN python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
COPY monitor.py tracker.py watchlist.json ./
RUN useradd --uid 10001 --create-home monitor && mkdir /app/data && chown monitor:monitor /app/data
USER monitor
ENV PYTHONUNBUFFERED=1
CMD ["python", "tracker.py", "run"]
