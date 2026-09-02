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
    fonts-liberation \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

# Copia e instala as dependencias do Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código da aplicação
COPY . .
RUN chmod +x start.sh

# Comando de inicialização
CMD ["./start.sh"]
