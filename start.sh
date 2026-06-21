#!/bin/bash

# FVX Template — backend start script
# Usage: ./start.sh [local|remote]

set -e

MODE=${1:-local}
SKIP_SEEDS=${SKIP_SEEDS:-0}
RUN_SEEDS_REMOTE=${RUN_SEEDS_REMOTE:-0}

echo "========================================="
echo "FVX Suscription Admin Backend - Starting"
echo "Mode: $MODE"
echo "========================================="

print_env_instructions() {
    echo ""
    echo "Environment file (.env) setup"
    echo "----------------------------"
    echo "1) Copy the example file:"
    echo "   cp .env.example .env"
    echo ""
    echo "2) Edit .env with your values (DB, Redis, secret key, etc.)."
    echo ""
    echo "Notes:"
    echo "  - For local Docker, defaults usually work."
    echo "  - For remote/production, you MUST set secure values (DJANGO_SECRET_KEY, hosts, etc.)."
    echo ""
}

ensure_env_local() {
    if [ -f .env ]; then
        return 0
    fi
    if [ ! -f .env.example ]; then
        echo "❌ Error: .env not found and .env.example is missing."
        print_env_instructions
        exit 1
    fi
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "⚠️  .env created. Please review/edit it before continuing."
    print_env_instructions
}

# Docker / Postgres leen .env tal cual; un \r al final de la contraseña rompe el login.
normalize_env_crlf() {
    if [ ! -f .env ]; then
        return 0
    fi
    python3 -c "
from pathlib import Path
p = Path('.env')
t = p.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
p.write_text(t, encoding='utf-8', newline='\n')
"
}

ensure_env_remote() {
    if [ -f .env ]; then
        return 0
    fi
    echo "❌ Error: .env file not found (required for REMOTE mode)."
    if [ -f .env.example ]; then
        print_env_instructions
    else
        echo ""
        echo "Also missing: .env.example"
        echo "Create a .env file with production settings before continuing."
        echo ""
    fi
    exit 1
}

run_seeds_if_enabled() {
    if [ "$SKIP_SEEDS" = "1" ]; then
        echo "Skipping seed loading (SKIP_SEEDS=1)"
        return 0
    fi
    if [ ! -f "sql/run_seeds.sh" ]; then
        echo "Seed script not found: sql/run_seeds.sh (skipping)"
        return 0
    fi

    echo ""
    echo "Loading seed data..."
    bash "sql/run_seeds.sh"
    echo "✅ Seed data loaded"
}

# Espera a que el entrypoint del contenedor web termine migrate (evita carrera con run_seeds en hosts lentos / Windows).
wait_for_web_migrations() {
    local mode="${1:-local}"
    local max=180
    local n=0
    echo "Waiting for Django migrations (web container)..."
    while [ "$n" -lt "$max" ]; do
        if [ "$mode" = "remote" ]; then
            if docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web python manage.py migrate --check >/dev/null 2>&1; then
                echo "  ✓ Django migrations are applied"
                return 0
            fi
        else
            if docker compose exec -T web python manage.py migrate --check >/dev/null 2>&1; then
                echo "  ✓ Django migrations are applied"
                return 0
            fi
        fi
        n=$((n + 1))
        sleep 1
    done
    echo "  ❌ Timeout after ${max}s waiting for migrations. Check: docker compose logs web"
    return 1
}

if [ "$MODE" = "local" ]; then
    echo "Starting in LOCAL mode..."

    # Si el stack de este repo ya está arriba, un segundo ./start no aplica migraciones/código:
    # preferir ./update.sh local. No aborta; FVX_FORCE_START=1 silencia el aviso.
    if [ "${FVX_FORCE_START:-0}" != "1" ] && command -v docker >/dev/null 2>&1; then
        if docker compose ps -q 2>/dev/null | head -1 | grep -q .; then
            echo ""
            echo "ℹ️  [FVX] Contenedores Docker detectados para este proyecto. Si ya inicializó el entorno"
            echo "   y solo cambió código o modelos, use:  ./update.sh local"
            echo "   (rebuild, makemigrations, migrate). Inicio limpio:  docker compose down && ./start.sh local"
            echo "   Sin este mensaje:  FVX_FORCE_START=1 ./start.sh local"
            echo ""
        fi
    fi

    ensure_env_local
    normalize_env_crlf
    
    # Build and start containers
    echo "Building Docker containers..."
    docker compose build
    
    echo "Starting Docker containers..."
    docker compose up -d

    wait_for_web_migrations local
    run_seeds_if_enabled
    
    echo ""
    echo "✅ System started successfully!"
    echo ""
    echo "Services:"
    echo "  - API: http://localhost:8080"
    echo "  - Admin: http://localhost:8080/admin"
    echo "  - API Docs: http://localhost:8080/api/docs/"
    echo "  - PostgreSQL: localhost:5432"
    echo "  - Redis: localhost:6379"
    echo ""
    echo "Default superuser:"
    echo "  - Username: admin"
    echo "  - Password: admin123"
    echo ""
    echo "To view logs: docker compose logs -f"
    echo "To stop: docker compose down"
    
elif [ "$MODE" = "remote" ]; then
    echo "Starting in REMOTE mode..."
    
    ensure_env_remote
    normalize_env_crlf
    
    # Build and start with production settings
    echo "Building Docker containers for production..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml build
    
    echo "Starting Docker containers in production mode..."
    docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

    if [ "$RUN_SEEDS_REMOTE" = "1" ]; then
        wait_for_web_migrations remote
        run_seeds_if_enabled
    else
        echo "Skipping seed loading in REMOTE mode (set RUN_SEEDS_REMOTE=1 to enable)"
    fi
    
    echo ""
    echo "✅ System started in production mode!"
    echo ""
    echo "Services (host port):"
    echo "  - API: http://localhost:8080"
    echo "  - Admin: http://localhost:8080/admin"
    echo "  - API Docs: http://localhost:8080/api/docs/"
    echo ""
    echo "To view logs: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"
    
else
    echo "❌ Invalid mode: $MODE"
    echo "Usage: ./start.sh [local|remote]"
    exit 1
fi
