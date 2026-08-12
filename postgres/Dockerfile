FROM debian:bookworm-slim

ENV POSTGRES_USER=telemops \
    POSTGRES_PASSWORD=telemops_dev \
    POSTGRES_DB=telemops \
    PGDATA=/var/lib/postgresql/data

RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql postgresql-contrib && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5432
ENTRYPOINT ["/entrypoint.sh"]
