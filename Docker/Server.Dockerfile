FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /Verdict

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn==26.2.0

COPY OpenBench ./OpenBench
COPY OpenSite ./OpenSite
COPY Templates ./Templates
COPY Config ./Config
COPY Engines ./Engines
COPY Books ./Books
COPY manage.py LICENSE ./

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn OpenSite.wsgi:application --bind 0.0.0.0:8000 --workers 1 --threads 4 --access-logfile - --error-logfile -"]
