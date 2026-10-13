FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
# ARG lets you override at build time: docker build --build-arg REQ=production.txt .
ARG REQ=development.txt
RUN pip install -r requirements/${REQ}

# Heatmap backdrop screenshots (apps/heatmap/capture.py). Off for a bare
# `docker build` and the dev compose, ON in both production compose files:
# Chromium and its system libraries add roughly 400MB to an image that api,
# celery and celery-beat all share. Without it the heatmap still renders — the
# capture task records `unavailable` and the dashboard says so rather than
# spinning. Opt production out with `WITH_CHROMIUM=0 ./deploy.sh`, or by putting
# WITH_CHROMIUM=0 in `.env` on the server — the compose files pass it through
# to every service as a build arg.
#
# It has to reach the celery image, which runs the capture, *and* the api
# image, which is what reports whether capture is available and answers 503
# when it is not. Both get it because they share one build.
#
# `playwright install --with-deps` runs its own `apt-get update` before pulling
# Chromium's system libraries, so the cleared apt lists above do not break it —
# but they have to be cleared again after, or the image carries the package
# index as well as the browser.
ARG WITH_CHROMIUM=0
RUN if [ "$WITH_CHROMIUM" = "1" ]; then \
        pip install playwright==1.49.1 && \
        playwright install --with-deps chromium && \
        rm -rf /var/lib/apt/lists/*; \
    fi

COPY . .

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "120"]
