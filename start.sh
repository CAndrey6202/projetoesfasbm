#!/usr/bin/env bash
set -e

echo "Rodando migrações do banco de dados..."
FLASK_APP=backend.app flask db upgrade

echo "Iniciando worker de background..."
nohup python worker.py > /opt/render/project/src/worker.log 2>&1 &

echo "Iniciando Gunicorn..."
exec gunicorn --workers 2 --threads 4 --timeout 120 --max-requests 500 --max-requests-jitter 50 "backend.app:create_app()"