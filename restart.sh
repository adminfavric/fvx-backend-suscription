#!/bin/bash

# FVX Suscription Admin Backend - Restart Script
# Usage: ./restart.sh [local|remote]

set -e

MODE=${1:-local}

compose() {
    if [ "$MODE" = "remote" ]; then
        docker compose -f docker-compose.yml -f docker-compose.prod.yml "$@"
    else
        docker compose "$@"
    fi
}

echo "========================================="
echo "FVX Suscription Admin Backend - Restarting"
echo "Mode: $MODE"
echo "========================================="

if [ "$MODE" = "remote" ] && [ ! -f .env ]; then
    echo "Error: .env file not found (required for remote)"
    exit 1
fi

if [ "$MODE" != "local" ] && [ "$MODE" != "remote" ]; then
    echo "Invalid mode: $MODE"
    echo "Usage: ./restart.sh [local|remote]"
    exit 1
fi

echo "Stopping containers..."
compose down

echo "Starting containers..."
compose up -d

echo ""
echo "System restarted successfully!"
echo ""
echo "Services (host port):"
echo "  - API: http://localhost:8080"
echo "  - Admin: http://localhost:8080/admin"
echo "  - API Docs: http://localhost:8080/api/docs/"
echo ""
if [ "$MODE" = "remote" ]; then
    echo "To view logs: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"
else
    echo "To view logs: docker compose logs -f"
fi
