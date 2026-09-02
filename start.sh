#!/usr/bin/env bash
set -e

echo "Rodando migrações do banco de dados..."
FLASK_APP=backend.app flask db upgrade

echo "Iniciando Supervisord..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf