#!/bin/bash

# FVX Suscription Admin Backend - Update Script
# Usage: ./update.sh [local|remote]

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
echo "FVX Suscription Admin Backend - Updating"
echo "Mode: $MODE"
echo "========================================="

if [ "$MODE" = "remote" ] && [ ! -f .env ]; then
    echo "Error: .env file not found (required for remote)"
    exit 1
fi

if [ "$MODE" != "local" ] && [ "$MODE" != "remote" ]; then
    echo "Invalid mode: $MODE"
    echo "Usage: ./update.sh [local|remote]"
    exit 1
fi

echo "Pulling latest changes..."
# git pull origin main

echo "Stopping containers..."
compose down

echo "Rebuilding containers..."
compose build --no-cache

echo "Starting containers..."
compose up -d

echo "Running makemigrations..."
compose exec web python manage.py makemigrations

echo "Running migrations..."
compose exec web python manage.py migrate

echo "Collecting static files..."
compose exec web python manage.py collectstatic --noinput

echo "Compiling messages..."
compose exec web python manage.py compilemessages

echo ""
echo "System updated successfully!"
echo ""
if [ "$MODE" = "remote" ]; then
    echo "To view logs: docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f"
else
    echo "To view logs: docker compose logs -f"
fi
