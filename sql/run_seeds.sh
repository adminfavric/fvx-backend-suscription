#!/bin/bash
# ============================================================================
# FVX Template — run optional seed SQL files
#
# Usage (desde el host, con DB en Docker):
#   cd fvx-backend && bash sql/run_seeds.sh
#
# Variables opcionales (coinciden con docker-compose / .env por defecto):
#   POSTGRES_USER   (default: fvx_user)
#   POSTGRES_DB     (default: fvx_backend_db)
#
# Lee variables desde .env si existe.
#
# Ejemplo manual:
#   docker compose exec -T db psql -U fvx_user -d fvx_backend_db -f /dev/stdin < sql/03_nav_menu.sql
#
# Idempotente: cada seed usa upsert por slug, así que se puede correr varias veces sin duplicar.
# ============================================================================

set -euo pipefail

echo "=== FVX Suscription Admin Backend - Seed Data Loader ==="
echo ""

SQL_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$(dirname "$SQL_DIR")"

if [ -f "$BACKEND_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$BACKEND_DIR/.env"
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-fvx_suscription_user}"
POSTGRES_DB="${POSTGRES_DB:-fvx_suscription_db}"

# Salida de psql vía Docker en Windows puede traer CRLF; normalizar evita falsos negativos en grep.
psql_trim() {
    tr -d '\r' | tr -d '[:space:]'
}

psql_exec() {
    local sql="$1"
    (cd "$BACKEND_DIR" && docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "$sql")
}

pgt_wait_ready() {
    echo "Waiting for database..."
    for _ in {1..120}; do
        if psql_exec "SELECT 1;" 2>/dev/null | psql_trim | grep -q '^1$'; then
            echo "  ✓ Database is reachable"
            return 0
        fi
        sleep 1
    done
    echo "❌ Database not reachable after 120s"
    return 1
}

wait_for_table() {
    local table="$1"
    local max=180
    local i=0
    while [ "$i" -lt "$max" ]; do
        if psql_exec "SELECT to_regclass('public.$table') IS NOT NULL;" 2>/dev/null | psql_trim | grep -q '^t$'; then
            return 0
        fi
        i=$((i + 1))
        sleep 1
    done
    echo "❌ Table $table not found after ${max}s"
    return 1
}

psql_seed() {
    local file="$1"
    (cd "$BACKEND_DIR" && docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /dev/stdin) < "$SQL_DIR/$file"
}

FILES=(
    "03_nav_menu.sql"
)

pgt_wait_ready
wait_for_table "django_migrations"
wait_for_table "api_menu"

for file in "${FILES[@]}"; do
    echo "→ Loading $file ..."
    psql_seed "$file"
    echo "  ✓ $file loaded"
    echo ""
done

echo "=== All seed data loaded successfully ==="
