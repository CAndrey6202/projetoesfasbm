FROM python:3.10-slim

WORKDIR /opt/render/project/src

# Instala as dependencias do sistema necessarias para o WeasyPrint (Pango, Cairo, etc)
RUN apt-get update && apt-get install -y \
    build-essential \
    python3-dev \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    python3-cffi \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependencias do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do codigo da aplicacao
COPY . .

# Comando de inicializacao: roda as migracoes, inicia o worker em background e o gunicorn
CMD FLASK_APP=backend.app flask db upgrade && python worker.py & gunicorn --workers 2 --threads 4 --timeout 120 --max-requests 500 --max-requests-jitter 50 "backend.app:create_app()"
