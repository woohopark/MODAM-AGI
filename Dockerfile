# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
WORKDIR /app
RUN --mount=type=secret,id=proxy_ca,required=true \
    PIP_CERT=/run/secrets/proxy_ca pip install --no-cache-dir uv==0.12.19
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=secret,id=proxy_ca,required=true \
    SSL_CERT_FILE=/run/secrets/proxy_ca uv sync --frozen --no-dev
COPY migrations ./migrations
COPY alembic.ini ./
ENV PATH=/app/.venv/bin:$PATH MODAM_API_HOST=0.0.0.0
RUN useradd --uid 10001 --create-home modam
RUN chmod -R a+rX /app
USER modam
EXPOSE 8000
CMD ["modam-api"]
