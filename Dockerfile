# Imagem da Nami. A base python:3.13-slim é multi-arquitetura: o mesmo arquivo
# funciona no Orange Pi (ARM64) e num PC comum (x86).
FROM python:3.13-slim

# unar: abre arquivos .cbr (RAR). Software livre, do repositório oficial do Debian.
RUN apt-get update \
    && apt-get install -y --no-install-recommends unar \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NAMI_DATA_DIR=/data

WORKDIR /app

# Dependências primeiro: se só o código mudar, o Docker reaproveita esta etapa.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

# Roda sem ser root: se alguém achar uma falha no app, não ganha o sistema todo.
RUN useradd --create-home --uid 1000 nami \
    && mkdir -p /data \
    && chown nami:nami /data
USER nami

VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# - Um worker só: o cache e os limites ficam na memória do processo, e vários
#   workers multiplicariam as chamadas ao MangaDex.
# - --proxy-headers: usa o IP real que o Caddy/Cloudflare informa. É seguro
#   porque a porta 8000 não fica exposta pra fora (só o proxy alcança o app).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
