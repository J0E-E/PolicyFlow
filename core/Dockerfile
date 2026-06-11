FROM python:3.12-slim

# curl is used by the docker-compose container health check that hits /api/health.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY app ./app

# Short commit SHA injected at build time by Epic 8's CodeBuild (--build-arg
# GIT_SHA=<sha>); defaults to "dev" for local builds. The app reads APP_VERSION.
ARG GIT_SHA=dev
ENV APP_VERSION=${GIT_SHA}

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
