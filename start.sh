#!/usr/bin/env bash

export MALLOC_ARENA_MAX=2
export ENABLE_IN_PROCESS_WORKER=1

echo "Iniciando Gunicorn (processo unico com worker em thread interna) na porta ${PORT:-10000}..."
exec gunicorn --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 4 --timeout 120 --max-requests 300 --max-requests-jitter 30 "backend.app:create_app()"
