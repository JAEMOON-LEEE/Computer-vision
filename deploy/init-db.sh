#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=app_password="$APP_PASSWORD" <<'SQL'
CREATE ROLE twinsight LOGIN PASSWORD :'app_password';
ALTER DATABASE twinsight OWNER TO twinsight;
SQL
