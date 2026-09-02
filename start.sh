#!/usr/bin/env bash
set -e

echo "Rodando migrações do banco de dados..."
FLASK_APP=backend.app flask db upgrade

echo "Iniciando worker de background..."
python worker.py &

echo "Iniciando Gunicorn..."
exec gunicorn --workers 2 --threads 4 --timeout 120 --max-requests 500 --max-requests-jitter 50 "backend.app:create_app()"
