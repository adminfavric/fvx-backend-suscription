#!/bin/bash
set -e

# .env con CRLF (p. ej. Windows) deja POSTGRES_PASSWORD=…\r → Postgres y Django
# usan contraseñas distintas. SOLO un contenedor (el de RUN_MIGRATIONS=true)
# normaliza el .env. Si esto se hace desde los tres contenedores simultáneos
# (entrypoint compartido), la lectura/escritura concurrente no es atómica y
# trunca el .env a 0 bytes — bug reproducido en abril 2026. Atomicidad vía
# write-temp-then-rename, además de la gate.
if [ "${RUN_MIGRATIONS:-false}" = "true" ] && [ -f /app/.env ]; then
  python3 -c "
import os
from pathlib import Path
p = Path('/app/.env')
t = p.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
tmp = p.with_suffix(p.suffix + '.tmp')
tmp.write_text(t, encoding='utf-8', newline='\n')
os.replace(tmp, p)  # atomic on POSIX
"
fi

# SOLO en dev: con el bind `.:/app` la imagen puede quedar desactualizada vs
# `requirements.txt`, así que reinstalamos al arrancar (evita reconstruir tras
# cada cambio de paquetes). En prod (DJANGO_DEBUG != true) la imagen es la fuente
# de verdad y NO se reinstala: arranque más rápido y reproducible.
case "${DJANGO_DEBUG:-False}" in
  [Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss])
    echo "Installing Python dependencies (dev)..."
    pip install --no-cache-dir -r /app/requirements.txt
    ;;
  *)
    echo "Skipping pip install (prod: image is the source of truth)."
    ;;
esac

echo "Waiting for PostgreSQL..."
while ! nc -z $POSTGRES_HOST $POSTGRES_PORT; do
  sleep 0.1
done
echo "PostgreSQL started"

# Migraciones + bootstrap (superuser, static) SOLO en el contenedor que tenga
# RUN_MIGRATIONS=true (típicamente `web`). Si se deja correr en `web`,
# `celery_worker` y `celery_beat` simultáneamente, los tres compiten por
# crear las mismas tablas y el primer `create_model` que pierde la carrera
# revienta con `IntegrityError: pg_type_typname_nsp_index already exists`.
# La barrera evita esa condición y deja el setup en un único punto.
if [ "${RUN_MIGRATIONS:-false}" = "true" ]; then
    # NO se corre `makemigrations` en runtime: el template envía un único
    # `0001_initial` regenerado y generar migraciones al arrancar crearía
    # archivos no deseados y enmascararía drift. El CI valida con
    # `makemigrations --check --dry-run`. Aquí solo aplicamos.
    echo "Running migrate..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput

    echo "Creating superuser if not exists..."
    python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
    print('Superuser created: admin/admin123')
else:
    print('Superuser already exists')
END
else
    # Otros contenedores (Celery worker/beat) esperan a que `web` termine de
    # migrar antes de arrancar. Sondeo barato vía Django checks: si `migrate
    # --check` sale 0 ya está; si no, espera y reintenta.
    echo "RUN_MIGRATIONS!=true → waiting for migrations to be applied by web..."
    for i in $(seq 1 60); do
        if python manage.py migrate --check >/dev/null 2>&1; then
            echo "Migrations are up to date — proceeding."
            break
        fi
        sleep 2
    done
fi

echo "========================================="
if [ "$#" -gt 0 ]; then
  echo "Starting: $*"
else
  echo "Starting Django development server..."
  echo "API: http://localhost:8080"
  echo "Admin: http://localhost:8080/admin"
  echo "API Docs: http://localhost:8080/api/docs/"
  set -- python manage.py runserver 0.0.0.0:8080
fi
echo "========================================="
exec "$@"
