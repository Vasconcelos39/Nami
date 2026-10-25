# Imagem da Nami. A base python:3.13-slim é multi-arquitetura: o mesmo arquivo
# funciona no Orange Pi (ARM64) e num PC comum (x86).
FROM python:3.13-slim

# unar: abre arquivos .cbr (RAR). Software livre, do repositório oficial do Debian.
RUN apt-get update \
    && apt-get install -y --no-install-recommends unar \
    && rm -rf /var/lib/apt/lists/*

# TMPDIR: arquivos temporários (ex.: um .cbz sendo enviado) vão pro disco, em
# /data/tmp, e não pra memória do Orange Pi.
# FORWARDED_ALLOW_IPS: quem pode contar ao uvicorn o IP real do visitante (o
# cabeçalho X-Forwarded-For). Só as redes internas, onde ficam o NPM, o Caddy
# e o cloudflared. O proxy acrescenta o IP real no fim de uma lista que o
# visitante pode preencher; assim o uvicorn lê a lista de trás pra frente e
# para no primeiro IP de fora (com "*", ele pegaria o primeiro da lista, que
# qualquer um inventa). Dá pra trocar no compose, se o seu proxy estiver em
# outra rede.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    NAMI_DATA_DIR=/data \
    TMPDIR=/data/tmp \
    FORWARDED_ALLOW_IPS="127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7"

WORKDIR /app

# Dependências primeiro: se só o código mudar, o Docker reaproveita esta etapa.
# constraints.txt trava também as dependências das dependências, nas versões
# que foram testadas.
COPY requirements.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt

COPY alembic.ini .
COPY migrations ./migrations
COPY app ./app

# Roda sem ser root: se alguém achar uma falha no app, não ganha o sistema todo.
RUN useradd --create-home --uid 1000 nami \
    && mkdir -p /data/tmp \
    && chown -R nami:nami /data
USER nami

VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"

# - Um worker só: o cache e os limites ficam na memória do processo, e vários
#   workers multiplicariam as chamadas ao MangaDex.
# - --proxy-headers: usa o IP real que o proxy informa (veja FORWARDED_ALLOW_IPS
#   acima pra saber em quem ele confia).
# - --no-server-header: não conta pra quem acessa qual servidor está rodando.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--no-server-header"]
