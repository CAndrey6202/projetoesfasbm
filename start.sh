#!/usr/bin/env bash

export MALLOC_ARENA_MAX=2

echo "Agendando migracoes e worker em background (apos boot do Gunicorn)..."
(
    sleep 15
    FLASK_APP=backend.app flask db upgrade || echo "Aviso: flask db upgrade retornou erro, prosseguindo..."
    echo "Iniciando worker de background..."
    exec python worker.py > /opt/render/project/src/worker.log 2>&1
) &

echo "Iniciando Gunicorn na porta ${PORT:-10000}..."
exec gunicorn --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 4 --timeout 120 --max-requests 300 --max-requests-jitter 30 "backend.app:create_app()"
