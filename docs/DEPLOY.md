# Colocando a Nami no Orange Pi

Passo a passo pra deixar a Nami rodando no Orange Pi, acessível de qualquer
lugar por HTTPS. Os comandos são digitados no terminal do Orange Pi (direto
nele ou por SSH).

## 0. O que você precisa

- **Orange Pi com Linux 64-bit** (Armbian, Ubuntu ou Debian). Confira com
  `uname -m`: tem que aparecer `aarch64`.
- **1 GB de RAM ou mais.**
- **Espaço em disco** pra sua biblioteca. Cartão SD funciona, mas um SSD/pendrive
  aguenta melhor escrita frequente.
- **Um endereço (domínio).** Dá pra pegar um grátis no [DuckDNS](https://www.duckdns.org),
  tipo `nami-fulano.duckdns.org`.

### Caddy ou Cloudflare Tunnel?

O site precisa ser alcançável de fora. Há dois jeitos, e a Nami já vem pronta pros dois:

| | **Caddy** (`caddy`) | **Cloudflare Tunnel** (`tunel`) |
|---|---|---|
| Precisa abrir portas no roteador | sim (80 e 443) | não |
| Funciona com CGNAT | não | sim |
| HTTPS | automático (Let's Encrypt) | automático (Cloudflare) |
| Depende de terceiros | não | sim, o tráfego passa pela Cloudflare |
| Domínio | qualquer um (DuckDNS serve) | precisa estar na Cloudflare |

**Como saber se você está em CGNAT.** Muitas operadoras no Brasil usam CGNAT:
o roteador não recebe um IP público próprio, e aí abrir porta não adianta.
Abra a página de status do seu roteador e veja o "IP WAN". Compare com o IP que
aparece em https://ifconfig.me.

- **Se forem diferentes**, ou se o IP WAN começar com `100.64` a `100.127`,
  você está em CGNAT. Use o **túnel**, ou peça à operadora um IP público
  (algumas liberam de graça).

## 1. Instalar o Docker

Pelo script oficial do Docker (documentado em https://docs.docker.com/engine/install/):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Saia e entre de novo no terminal (pra valer a permissão) e teste com
`docker compose version`.

## 2. Baixar a Nami

```bash
git clone https://github.com/vasconcelos39/nami.git
cd nami
cp .env.example .env
```

## 3. Configurar o `.env`

Abra com `nano .env` e preencha a parte **Deploy** no fim do arquivo.

**Com Caddy:**

```
COMPOSE_PROFILES=caddy
NAMI_DOMINIO=nami-fulano.duckdns.org
NAMI_EMAIL=seu-email@exemplo.com
```

- **No roteador:** encaminhe as portas **80** e **443** (TCP; a 443 também em UDP)
  pro IP do Orange Pi na sua rede. O IP aparece em `hostname -I`. Vale fixar esse IP
  no roteador (reserva de DHCP).
- **No DuckDNS:** aponte o domínio pro seu IP público. Como o IP de casa muda,
  deixe o Orange Pi avisando o DuckDNS a cada 5 minutos. Rode `crontab -e` e
  acrescente a linha abaixo (trocando o domínio e o token do seu painel do DuckDNS):

  ```
  */5 * * * * curl -s "https://www.duckdns.org/update?domains=nami-fulano&token=SEU-TOKEN&ip=" >/dev/null
  ```

**Com Cloudflare Tunnel:**

1. No painel da Cloudflare: **Zero Trust → Networks → Tunnels → Create a tunnel**
   (tipo *Cloudflared*).
2. Copie o **token** que aparece no comando de instalação (o texto longo depois
   de `--token`).
3. Em **Public Hostname**, adicione o seu domínio com serviço **HTTP** e URL
   `nami:8000`.
4. No `.env`:

   ```
   COMPOSE_PROFILES=tunel
   CLOUDFLARE_TUNNEL_TOKEN=cole-o-token-aqui
   ```

Não precisa abrir porta nenhuma.

Outras opções do `.env` (idiomas, limites, cadastro aberto) estão explicadas no
próprio arquivo.

## 4. Subir

```bash
docker compose up -d --build
```

A primeira vez demora alguns minutos (o Orange Pi monta a imagem). Pra
acompanhar: `docker compose logs -f`. Quando aparecer
`Application startup complete`, está no ar.

## 5. Criar a sua conta de admin

```bash
docker compose exec nami python -m app.cli criar-admin
```

O comando pergunta o nome e a senha. Depois, entre no site e abra `/admin`:
é por lá que você envia os .cbz/.cbr e gerencia os usuários.

> Por que um comando, e não "a primeira conta vira admin"? Com o site aberto
> na internet, um estranho poderia se cadastrar antes de você.

## 6. Depois que todo mundo tiver conta

Feche o cadastro pra ninguém de fora criar conta. No `.env`:

```
NAMI_CADASTRO_ABERTO=false
```

e aplique com `docker compose up -d`.

## 7. Instalar no celular

Com o site no ar em HTTPS, abra o seu domínio no celular:

- **Android:** aparece um convite "Instalar" na página inicial (ou use
  "Instalar app" no menu do Chrome).
- **iPhone:** Safari → Compartilhar → "Adicionar à Tela de Início".

O ícone da Nami vai pra tela inicial e o site abre como app, sem a barra do
navegador. Só funciona com HTTPS: pelo IP da rede (`http://192.168…`) o
navegador não oferece instalar.

## Dia a dia

| Tarefa | Comando |
|---|---|
| Ver os logs | `docker compose logs -f nami` |
| Atualizar a Nami | `git pull` e depois `docker compose up -d --build` |
| Reiniciar | `docker compose restart nami` |
| Parar tudo | `docker compose down` (os dados ficam guardados) |
| Esqueceram a senha | painel `/admin/usuarios` → "Redefinir senha" |
| Você perdeu o seu admin | `docker compose exec nami python -m app.cli redefinir-senha SEU-NOME` |

As atualizações do banco (migrations) rodam sozinhas quando a Nami inicia.

### Backup

Os dados ficam num volume do Docker (`nami_dados`): banco, biblioteca e cache.

```bash
# cópia do banco (contas, progresso, favoritos, dados das obras)
docker compose exec nami python -m app.cli backup
docker compose cp nami:/data/backups ./backups

# páginas da biblioteca local (só se você não tiver os .cbz/.cbr originais guardados)
docker compose cp nami:/data/biblioteca ./biblioteca-backup
```

Guarde as cópias fora do Orange Pi (no PC, num HD externo…).

## Segurança

- **Deixe abertas pra internet só as portas 80/443** (ou nenhuma, com o túnel).
  O SSH (porta 22) não precisa ficar exposto: use-o só na rede de casa.
- **Mantenha o sistema atualizado:** `sudo apt update && sudo apt upgrade` de vez em quando.
- **O que a Nami já faz sozinha:**
  - HTTPS e cookie de login só por HTTPS;
  - limite de requisições por IP (120 páginas e 900 imagens por minuto, ajustáveis
    no `.env`) e bloqueio após 10 senhas erradas;
  - cabeçalhos contra embutir o site em outros sites;
  - pedido pros buscadores não indexarem o site.
- **O tamanho máximo de envio** de arquivos é 1 GB (`NAMI_UPLOAD_MAX_MB` e o
  `request_body` no `Caddyfile`). Se mudar um, mude o outro.

## Se algo der errado

- **O site não abre de fora, mas abre na rede de casa** (`http://IP-DO-PI` não
  funciona; teste com `curl -I http://localhost` no Pi): confira o
  encaminhamento de portas e se você não está em CGNAT.
- **Erro de certificado no Caddy:** o domínio precisa apontar pro seu IP
  público *antes* de subir. Veja `docker compose logs caddy`.
- **"Fonte indisponível"** em todo lugar: o Pi está sem internet ou o MangaDex
  está fora do ar. A biblioteca local continua funcionando.
- **.cbr não abre:** confira se o arquivo não está corrompido abrindo no PC.
  Dentro do Docker o programa que abre RAR (`unar`) já vem instalado.
