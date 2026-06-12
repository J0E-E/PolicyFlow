# Base image pulled from Amazon ECR Public's mirror of the Docker Official Images
# (not Docker Hub) so CodeBuild's shared-IP fleet doesn't hit Docker Hub's
# anonymous pull rate limit. Same official image + tag; works locally too.
FROM public.ecr.aws/docker/library/python:3.12-slim

# curl is used by the docker-compose container health check that hits /api/health.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY app ./app

# Alembic config and migrations, run by the entrypoint before the app serves.
COPY alembic.ini ./
COPY alembic ./alembic

# Entrypoint runs migrate -> seed -> serve. Make it executable.
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

# Short commit SHA injected at build time by Epic 8's CodeBuild (--build-arg
# GIT_SHA=<sha>); defaults to "dev" for local builds. The app reads APP_VERSION.
ARG GIT_SHA=dev
ENV APP_VERSION=${GIT_SHA}

EXPOSE 8000

# The entrypoint migrates and seeds, then exec's this CMD (uvicorn). Invoke it
# through /bin/sh so a stray CR in the shebang can't break interpreter resolution.
ENTRYPOINT ["/bin/sh", "./entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
