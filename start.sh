#!/usr/bin/env bash

echo "Iniciando migracoes e worker em background para liberar a porta rapidamente..."
(
    FLASK_APP=backend.app flask db upgrade || echo "Aviso: flask db upgrade retornou erro, prosseguindo..."
    echo "Iniciando worker de background..."
    exec python worker.py > /opt/render/project/src/worker.log 2>&1
) &

echo "Iniciando Gunicorn na porta ${PORT:-10000}..."
exec gunicorn --bind "0.0.0.0:${PORT:-10000}" --workers "${WEB_CONCURRENCY:-1}" --threads 8 --timeout 120 --max-requests 500 --max-requests-jitter 50 "backend.app:create_app()"
