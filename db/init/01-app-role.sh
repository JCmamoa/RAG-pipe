#!/bin/sh
# Runs only on the FIRST initialization of the Postgres volume.
# Creates the runtime role. Without superuser and BYPASSRLS, the row-level security policies apply.
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE ROLE rag_app LOGIN PASSWORD '${APP_DB_PASSWORD}' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO rag_app;
EOSQL
