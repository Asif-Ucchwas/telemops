#!/bin/bash
set -e

PG_VERSION=$(ls /usr/lib/postgresql)
PG_BIN=/usr/lib/postgresql/$PG_VERSION/bin

# Named volumes mount as root-owned by default; fix that before postgres tries to use it
chown -R postgres:postgres "$PGDATA"
chmod 700 "$PGDATA"

if [ ! -s "$PGDATA/PG_VERSION" ]; then
  echo "[entrypoint] Initializing new Postgres cluster in $PGDATA"
  su postgres -c "$PG_BIN/initdb -D $PGDATA --username=postgres"

  echo "listen_addresses='*'" >> "$PGDATA/postgresql.conf"
  echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"

  su postgres -c "$PG_BIN/pg_ctl -D $PGDATA -w start"

  su postgres -c "psql --username postgres -c \"ALTER USER postgres PASSWORD '$POSTGRES_PASSWORD';\""
  su postgres -c "psql --username postgres -c \"CREATE USER $POSTGRES_USER WITH SUPERUSER PASSWORD '$POSTGRES_PASSWORD';\""
  su postgres -c "psql --username postgres -c \"CREATE DATABASE $POSTGRES_DB OWNER $POSTGRES_USER;\""

  su postgres -c "$PG_BIN/pg_ctl -D $PGDATA -m fast -w stop"
  echo "[entrypoint] Initialization complete"
fi

echo "[entrypoint] Starting Postgres"
exec su postgres -c "$PG_BIN/postgres -D $PGDATA -c listen_addresses='*'"
