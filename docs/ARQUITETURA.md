# Arquitetura da Nami

Leitor self-hosted de mangás, manhwas e HQs, pensado pra rodar num Orange Pi
(ARM64) exposto na internet.

## Princípio central

A Nami **não guarda scans**. O conteúdo vem de duas fontes legítimas:

1. **API oficial do MangaDex.** As páginas passam pelo servidor da Nami em
   *streaming* (proxy) e não são gravadas em disco. O proxy é exigência do
   próprio MangaDex: eles servem imagem errada pra hotlink e não aceitam chamadas
   do navegador de outros sites (ver "Regras do MangaDex" abaixo).
2. **Arquivos locais** (.cbz/.cbr) que o dono do servidor possui, enviados pelo
   painel de admin (Fase 3).

## Fases

| Fase | Conteúdo | Estado |
|---|---|---|
| 1 | Adaptador MangaDex, busca, leitor, filtro de classificação | pronta |
| 2 | Contas, histórico, progresso, favoritos, preferência +18 | pronta |
| 3 | Biblioteca local (.cbz/.cbr) + painel de admin | pronta |
| 4 | Regras finais do +18, proteções, Docker, HTTPS, deploy | pronta (o Docker ainda não rodou num Orange Pi de verdade) |
| 5 | Celular e app instalável, AniList (links oficiais e capítulos faltando), reportes, obras por página | pronta |
| 6 | Suporte (tickets em forma de chat), auditoria de segurança, clique que rola no leitor, comando `importar` | pronta |
| 7 | Autocompletar na busca, aviso de obra que só dá pra ler fora, página por usuário no admin, verificação de idade, IP real atrás do NPM | pronta |
| 8 | Área de Novidades (posts do admin sobre o que mudou, com rascunho e bolinha no menu) | pronta |
| 9 | Área madura separada (senha pra entrar, tema preto, histórico e favoritos próprios); site normal sem nada adulto; Esc sai do capítulo | pronta |

Deploy passo a passo: [DEPLOY.md](DEPLOY.md).

## Pastas

```
app/
  main.py            monta o app: banco, fontes, rotas, páginas de erro
  config.py          configurações (variáveis NAMI_* ou .env)
  db.py              conexão SQLite e migrations automáticas no início
  models.py          tabelas do banco
  dominio.py         formato interno: Obra, Capitulo, Pagina, Classificacao...
  cache.py           cache em memória com validade
  dependencias.py    o que as rotas recebem prontas (fontes, usuário, banco)
  renderizar.py      templates Jinja
  cli.py             comandos de terminal (criar-admin, promover, redefinir-senha, backup, importar)
  fontes/
    base.py          o contrato que toda fonte cumpre
    registro.py      quais fontes estão ligadas
    mangadex.py      adaptador do MangaDex
    local.py         adaptador da biblioteca local (banco + disco)
    limitador.py     ritmo das chamadas ao MangaDex (e ao AniList)
  catalogos/
    anilist.py       metadados do AniList: total de capítulos, links oficiais, busca
  servicos/
    visibilidade.py  quem pode ver qual classificação (regra única)
    imagens.py       cache de capas do MangaDex em disco
    auth.py          senhas, sessões, limite de tentativas de login
    estante.py       progresso, histórico e favoritos de cada usuário
    biblioteca.py    abrir .cbz/.cbr, validar imagens, gerar capa, ComicInfo.xml
    acervo.py        criar/editar/remover obras e capítulos locais
    protecao.py      limite de requisições por IP e cabeçalhos de segurança
    cobertura.py     compara os capítulos daqui com a obra original
    reportes.py      avisos de problema enviados pelos usuários
    suporte.py       tickets de suporte (quem vê, limites, status)
    maioridade.py    verificação de idade pra liberar a área madura
    area_madura.py   entrar com senha, prazo de 30 min e sair da área madura
    noticias.py      posts de Novidades e o texto simples (escapa tudo)
  rotas/             catalogo (início, seções, busca, sugestões, obra), leitor,
                     midia (proxy), conta, estante, reportes, suporte, noticias, madura, admin
  templates/         HTML (admin/ = painel, suporte/ = chat de suporte)
  static/            CSS; JS do site (nami.js), do autocompletar da busca, do leitor,
                     do painel, do chat de suporte e o service worker (sw.js); manifest e tela offline;
                     marca/ (logos já tratados)
requirements.txt     dependências diretas; constraints.txt trava todas as versões
assets/              arte original da marca (os PNGs que você mandou)
migrations/          Alembic (alterações do banco versionadas)
tests/               testes (MangaDex e AniList simulados, sem internet)
data/                fora do git: nami.db, biblioteca/, cache/capas/, tmp/, backups/
Dockerfile, docker-compose.yml, Caddyfile   deploy (Fase 4)
```

## Fontes plugáveis

Cada fonte é uma classe que cumpre `app/fontes/base.py:Fonte` e devolve os
tipos de `app/dominio.py`. Rotas, templates e leitor só conhecem esses tipos.
Pra adicionar uma fonte: criar a classe e registrá-la em
`app/fontes/registro.py`.

As URLs de imagem que uma fonte devolve são **sempre da própria Nami**
(`/img/{fonte}/{capitulo}/{n}` e `/capa/{fonte}/{obra}`). O navegador nunca
recebe a URL de origem e nunca manda uma URL pro servidor. Assim o servidor não
vira um proxy aberto que qualquer pessoa usa pra baixar coisas da internet.

## Classificação etária

Regra única em `app/servicos/visibilidade.py`. São dois "sites" separados:

| Onde | Quem | Vê |
|---|---|---|
| Site normal | visitante | safe |
| Site normal | logado | safe + suggestive |
| Área madura (`/madura`) | idade confirmada + senha digitada neste aparelho | **só** erotica e pornographic |

- O site normal nunca tem nada adulto: nem nas seções, nem na busca, nem no
  autocompletar, nem no histórico ou nos favoritos. Obra adulta aberta pelo
  endereço normal (`/obra/...`, `/ler/...`) responde 404, mesmo com a área
  madura aberta. E a área madura não mostra obra que não é adulta.
- Cada área tem a sua busca, o seu histórico e os seus favoritos: a separação é
  pela classificação da obra, então nada precisou mudar no banco.
- A checagem acontece na listagem, na página da obra, no leitor **e em cada
  imagem** (proxy de páginas e de capas): imagem adulta só com a área aberta.
- Página proibida responde 404, não 403, pra não revelar que existe (inclusive
  `/madura` pra quem não tem acesso).
- Ser admin não libera conteúdo adulto: o admin segue as mesmas regras nas
  páginas do site (o painel lista todas as obras locais, pra poder gerenciar).

### Área madura (`/madura`)

`app/servicos/area_madura.py` e `app/rotas/madura.py`. As páginas são as
mesmas do site normal (início, busca, obra, leitor, histórico, favoritos),
chamadas com `madura=True`, num tema preto com destaque vermelho
(`<html data-area="madura">`) e com menu próprio.

- **Entrar:** o link "Área madura" fica ao lado de "Verificação de idade", no
  fim de "Sua conta", e só aparece pra quem confirmou a idade. Ele sempre pede
  a senha da conta (senha errada conta no limite do login).
- **Prazo:** a área abre só na sessão de login daquele aparelho
  (`sessao.madura_ate`) e fecha sozinha depois de 30 minutos sem abrir nenhuma
  página lá dentro (cada página e cada página virada no leitor empurram o prazo).
  "Sair da área madura" fecha na hora; sair da conta também.
- **Bloqueio:** um admin pode bloquear a área de qualquer conta, e a pessoa sai
  na hora.
- **Links:** `raiz_de(obra)` (global do Jinja) monta o endereço certo: obra
  adulta sempre em `/madura/...`.

### Verificação de idade (`/conta/maioridade`)

Nenhum site pequeno consegue provar a idade de alguém; a ideia é que liberar a
área madura deixe de ser "marcar uma caixinha" (`app/servicos/maioridade.py`):

- a opção não fica à vista: é um link pequeno ("Verificação de idade") no fim
  de "Sua conta", que abre uma página própria;
- pra liberar, a pessoa digita a **senha da conta** (quem pega um celular já
  logado não libera sozinho) e, na primeira vez, a **data de nascimento**; como
  acabou de digitar a senha, já entra direto na área madura;
- senha errada ali conta no mesmo limite do login (20 por conta a cada 15 min);
- uma data de menos de 18 anos **bloqueia a área madura da conta**: tentar de novo com
  outra data não adianta, só um admin desbloqueia (e aí a pessoa recomeça);
- a data de nascimento não é guardada, só o dia da confirmação;
- desativar não pede nada. Liberar de novo pede só a senha.

A migração 0004 zerou as confirmações antigas (feitas pela caixinha): quem
tinha o +18 ligado passa pela verificação nova.

Tipo da obra, pelo idioma original: japonês → mangá; coreano → manhwa; chinês →
manhua (aparece na seção Manhwas); qualquer outro → HQ.

## Banco de dados

```
fonte      id ('mangadex' | 'local'), nome, ativa
usuario    id, username (único, ignora maiúsculas), senha_hash, is_admin, ativo,
           maioridade_confirmada_em, mostrar_adulto, idioma_preferido, criado_em
sessao     token_hash (PK), usuario_id, criada_em, expira_em
obra       id, fonte_id, id_externo, titulo, autor, descricao, tipo, classificacao,
           status, ano, capa, anilist_id, criado_em, atualizado_em
                                                            [único: fonte_id + id_externo]
tag        id, nome (único)
obra_tag   obra_id, tag_id
capitulo   id, obra_id, id_externo, numero, volume, ordem, titulo, idioma, grupo,
           total_paginas, pasta, publicado_em               [único: obra_id + id_externo]
progresso  usuario_id, capitulo_id, pagina, concluido, atualizado_em
favorito   usuario_id, obra_id, criado_em
reporte    id, usuario_id, fonte_id, obra_externa, titulo, motivo, detalhe,
           criado_em, resolvido_em
ticket     id, usuario_id, assunto, status (aberto|respondido|fechado),
           criado_em, atualizado_em
mensagem_ticket  id, ticket_id, autor_id, do_suporte, texto, criado_em
```

Decisões:

- **Obras do MangaDex não são copiadas pro banco.** A busca vai direto na API.
  Só quando alguém favorita ou lê é gravada uma linha "leve"
  (`servicos/estante.py:guardar_obra`), porque progresso e favorito precisam
  de algo pra apontar. A cada leitura a linha é atualizada, então a
  classificação guardada acompanha a do MangaDex.
- **Sem tabela de páginas.** As locais ficam em pastas numeradas; as do
  MangaDex são buscadas na hora.
- **Sem tabela de histórico.** O histórico sai de `progresso` ordenado por
  data. Trade-off: guarda só a última leitura de cada capítulo, sem releituras.
- **Sem e-mail.** Trade-off: não há "esqueci minha senha"; quem reseta é o admin.
- **Sessão no banco** (o hash do token; o token fica só no cookie). Desativar
  uma conta derruba a sessão na hora, e um vazamento do banco não expõe sessões.
- Migrations com Alembic, aplicadas automaticamente quando o app inicia.

## Contas e segurança

- **Senhas** com argon2id (`argon2-cffi`, parâmetros da RFC 9106). No máximo 2
  hashes rodam ao mesmo tempo: cada um usa ~64 MB de RAM, e uma enxurrada de
  logins poderia derrubar o Orange Pi por falta de memória.
- **Login de nome inexistente** confere um hash falso, pra demorar o mesmo tanto
  que um login real (ninguém descobre quais nomes têm conta pelo tempo).
- **Limite de tentativas**, na memória: 10 logins errados por rede a cada 15 min,
  20 numa mesma conta (vindos de qualquer rede) e 5 contas novas por hora.
  "Rede" é o IP, ou o bloco /64 no IPv6 (cada conexão IPv6 tem milhões de
  endereços; contar um por um deixaria trocar de IP à vontade). Atrás do proxy
  HTTPS, o uvicorn recebe o IP real do visitante (`--proxy-headers`), mas só
  confia no cabeçalho `X-Forwarded-For` quando ele vem das redes internas
  (`FORWARDED_ALLOW_IPS` no Dockerfile: 10/8, 172.16/12, 192.168/16, fc00::/7).
  O proxy (NPM, Caddy, cloudflared) acrescenta o IP real no fim de uma lista
  que o visitante pode preencher; o uvicorn lê de trás pra frente e para no
  primeiro IP de fora. Com `*` (como era até a 0.6), ele pegava o primeiro da
  lista, que qualquer um inventa, e dava pra driblar os limites por IP.
  Trade-off do limite por conta: alguém pode bloquear o login de uma conta por
  15 minutos errando a senha dela de propósito; o admin sempre pode entrar
  pelo terminal (`redefinir-senha`).
- **Senhas comuns** ("12345678", "senha123"…) e senhas de um caractere repetido
  são recusadas.
- **"Sair de todos os outros aparelhos"** em "Sua conta" apaga as outras sessões.
- **Cookie de sessão** `nami_sessao`: `HttpOnly` (o JavaScript não lê),
  `SameSite=Lax` e `Secure` quando `NAMI_COOKIE_SEGURO=true`. Isso **precisa**
  ficar ligado em produção (Fase 4).
- **CSRF** (outro site enviando formulários em nome de quem está logado):
  além do `SameSite`, todo POST que o navegador marca como vindo de outro site
  é recusado: `Sec-Fetch-Site: cross-site`, ou `Origin` (ou, nos navegadores
  antigos, `Referer`) com outro endereço (`main.py:conferir_origem`). A
  comparação é pelo nome do site, sem a porta, porque proxies como o Nginx
  Proxy Manager repassam o `Host` sem ela.
- **Redirecionamento depois do login** só aceita caminhos deste site
  (`rotas/conta.py:destino_seguro`), pra não virar trampolim pra site falso.
- **Trocar a senha** derruba as sessões dos outros aparelhos.
- **Cadastro** aberto por padrão; `NAMI_CADASTRO_ABERTO=false` fecha depois
  que todo mundo que você quer tiver conta.
- **Maioridade** é autodeclarada (uma caixa de confirmação, com a data
  guardada). Trade-off: não é verificação de verdade, é o mesmo nível que o
  MangaDex e a maioria dos sites usam.
- **O primeiro admin** é criado pelo terminal (`python -m app.cli criar-admin`),
  nunca pelo site: com o servidor aberto, um estranho poderia se cadastrar
  antes de você e virar admin.

## Progresso de leitura

O leitor avisa a página atual (evento `nami:pagina`) e, com login, manda pro
servidor (`POST /progresso/...`) quando a pessoa para numa página por 1,5 s,
e na hora ao fechar a aba. Chegar na última página marca o capítulo como lido
(e ele continua lido mesmo se a pessoa voltar pro começo). O total de páginas
que vale é o da fonte, não o que o navegador manda.

## Biblioteca local

- Cada arquivo enviado vira um capítulo (ou volume). As páginas ficam em
  `data/biblioteca/<obra>/<capitulo>/0001.jpg…`; a capa em `data/biblioteca/<obra>/capa.jpg`.
- Obras e capítulos locais usam ids aleatórios de 32 caracteres (`uuid4`),
  que aparecem nas URLs (`/obra/local/<id>`).
- **.cbz = ZIP, .cbr = RAR.** O formato é descoberto pelos primeiros bytes,
  não pela extensão (muitos ".cbr" são ZIPs renomeados). ZIP o Python abre
  sozinho; RAR precisa do programa `unar` (vem no Docker) ou unrar/7z.
- **Cuidados com o arquivo enviado:** os nomes de dentro do ZIP nunca viram
  caminho no disco (as páginas são renomeadas), cada imagem é aberta pelo
  Pillow pra confirmar que é imagem, formatos estranhos (BMP, TIFF) viram JPEG,
  e há limites contra "bombas de compactação" (3000 páginas, 64 MB por página,
  4 GB descompactado).
- **Metadados:** o que o admin deixar em branco vem do `ComicInfo.xml` do
  arquivo, se existir. O número do capítulo/volume sai do ComicInfo ou do nome
  do arquivo (`Obra v02 c015.cbz`). Os botões "Buscar no AniList" e "Buscar no
  MangaDex" do painel preenchem o formulário com os dados de lá. Usar o AniList
  também guarda o `anilist_id`, que liga a obra local aos links oficiais e ao
  aviso de capítulos faltando (o campo aceita o número ou o link da obra).
- **Capa:** a primeira página (ou uma imagem enviada), reduzida pra 512×768;
  em webtoons (página muito alta), só o topo.
- **Trade-off:** o envio é processado na hora, dentro da própria requisição.
  Um volume de 200 MB pode levar alguns minutos no Orange Pi e o navegador
  fica esperando. Pra um admin só, é mais simples que uma fila de tarefas.
- **Pelo terminal:** `python -m app.cli importar CAMINHO...` faz o mesmo que o
  envio do painel, lendo os arquivos direto do disco do servidor (aceita
  pastas). Serve pra coleções inteiras e pra arquivos acima de 100 MB, que a
  Cloudflare recusa pelo túnel. Os arquivos originais ficam onde estavam.
- Na seção HQs, a aba "Biblioteca local" vem primeiro quando há HQs lá
  (quase não existe HQ no MangaDex). A busca procura nas duas fontes.

## Painel de admin (`/admin`)

- Biblioteca: enviar obra (um ou vários arquivos), editar dados e capa,
  adicionar/renomear/remover capítulos, remover obra (com confirmação).
- Usuários: a lista só mostra as contas; clicar numa abre a página dela, com
  um resumo (último login, aparelhos conectados, área madura, favoritos, tickets,
  reportes) e as ações: tornar/tirar admin, bloquear/desbloquear a área madura,
  desconectar dos aparelhos, redefinir senha (gera uma temporária mostrada uma
  vez só) e, separado, desativar/reativar (desconecta na hora). As ações que
  não dá pra desfazer na hora pedem confirmação.
- Reportes: os avisos de problema mandados pelos usuários, com "marcar como
  resolvido" e "reabrir". O painel mostra quantos estão em aberto.
- O admin não consegue tirar o próprio acesso nem desativar a própria conta.
- Pra qualquer outra conta, `/admin` responde 404.

## AniList e capítulos faltando

O MangaDex às vezes tem menos capítulos que a obra: obras licenciadas perdem
capítulos, e grupos de tradução param no meio. A página da obra compara o que
dá pra ler aqui com outras referências (`servicos/cobertura.py`):

- **Total da obra original:** do AniList (`chapters`) ou do MangaDex
  (`lastChapter`). Os dois só informam depois que a obra termina; pra obra em
  andamento não há total confiável em lugar nenhum.
- **Outros idiomas:** "em inglês dá pra ler até o cap. 450".
- **Tradução parada:** obra em andamento cujo último capítulo no idioma tem
  mais de um ano.

Com isso aparece um aviso e os links oficiais (botão "Ler no site oficial"):
os do MangaDex (`links.engtl`, `links.raw` e lojas) mais os "links externos"
do AniList (tipo `STREAMING` = dá pra ler lá; `INFO` = editora). Redes sociais
ficam de fora. A ordem segue os idiomas da pessoa, e leitura vem antes de loja.

Como a Nami encontra a obra no AniList: o MangaDex informa o id (`links.al`);
nas obras locais, o admin liga pelo painel. **Não há busca por título
automática**, porque um título parecido de outra obra daria aviso errado.

Regras do AniList (https://docs.anilist.co, *Terms of use* e *Rate limiting*):
uso grátis só não comercial; sem usar a API como armazenamento nem coletar o
catálogo em massa; limite de 30 consultas/min no modo "degradado" atual (o
normal é 90). A Nami consulta só a obra que alguém abriu, guarda a resposta
6 h na memória (falhas, 10 min), usa no máximo 25/min e respeita o
`Retry-After` de um 429. Se o AniList não responder, a página abre sem essa
parte. `NAMI_ANILIST_ATIVO=false` desliga tudo.

## Suporte

Área `/suporte` (só com login): a pessoa abre uma conversa (assunto +
mensagem) e os admins respondem, como num chat.

- **Quem vê:** quem abriu e os admins. Pra qualquer outra conta o ticket
  responde 404, nem confirma que o número existe.
- **Status:** "esperando o suporte" (a pessoa falou por último), "respondido"
  (o suporte falou por último) e "fechado" (qualquer um dos dois marca como
  resolvido; uma mensagem nova reabre). Um admin no próprio ticket fala como
  pessoa comum.
- **Avisos:** um número aparece no menu (e um ponto no ícone "Conta" do
  celular) quando há resposta nova; pros admins, quantos tickets esperam
  resposta. Não há e-mail nem notificação no celular.
- **Chat:** funciona sem JavaScript (formulário normal). Com ele,
  `static/js/suporte.js` manda a mensagem sem recarregar e busca as novas a
  cada 15 s, só com a aba visível. Os horários aparecem no fuso do aparelho.
  Trade-off: não é tempo real (WebSocket); 15 s de atraso não faz diferença
  pra suporte e evita deixar conexões abertas no Orange Pi.
- **Limites:** assunto de 3 a 120 caracteres, mensagem até 4000, no máximo 5
  conversas abertas por conta e 30 mensagens por hora (admins sem limite). O
  texto aparece sempre como texto (nunca como HTML).

## Novidades

Posts do admin contando, do jeito dele, o que mudou no site (`/novidades`,
escritos em `/admin/novidades`; regra em `app/servicos/noticias.py`).

- Rascunho (sem data de publicação) só os admins veem. "Publicar" marca a data;
  "Voltar pra rascunho" tira o post do ar.
- **Bolinha no menu:** cada conta guarda quando abriu `/novidades` pela última
  vez (`usuario.noticias_vistas_em`); post publicado depois disso acende a
  bolinha em "Novidades" (e no ícone "Conta" do celular) e ganha a marca "nova".
  Corrigir um post já publicado mantém a data, pra não acender de novo.
- **Texto simples, nunca HTML:** linha em branco separa parágrafos, linhas com
  `- ` viram lista, `**assim**` vira negrito e endereços http(s) viram links.
  Cada pedaço é escapado antes de virar HTML (o filtro `texto_simples` é o único
  lugar que monta HTML a partir de texto digitado; há testes de XSS).
- Só quem tem conta vê (o link fica no menu da conta).
- A migração 0005 deixa um rascunho do primeiro post, contando o que mudou desde
  a 0.6, quando o banco já tem contas (instalação nova começa vazia).

## Reportes

Botão "⚑ Reportar problema" na página da obra (só com login): capa errada,
capítulos faltando, informações erradas, classificação errada ou outro, com
um texto opcional (até 1000 caracteres). Mandar o mesmo aviso de novo, ainda
aberto, só atualiza o texto, e cada conta manda no máximo 10 por dia. Obra
adulta só pode ser reportada com a área madura aberta; obra escondida responde 404 também aqui. Obras do MangaDex
não ficam no banco, então o reporte guarda fonte + id + título.

## Celular e app instalável

- **Telas estreitas (até 720 px):** o topo vira uma linha só (marca e seções) e
  aparece uma barra fixa embaixo (Início, Buscar, Histórico, Favoritos, Conta),
  como num app. A busca vai pra própria página `/busca`; Admin e Sair ficam em
  "Sua conta". Capas em 3 colunas; na obra, capa pequena ao lado do título e
  sinopse cortada com "Ler mais".
- **Leitor:** deslizar o dedo vira a página no modo paginado (com zoom de
  pinça, o gesto só move a imagem); tocar nas laterais vira, no meio esconde as
  barras. Nas configurações, "Clique na página" troca isso por rolar um pedaço
  pra baixo (35%, 55% ou 80% da tela); no modo paginado, quando a página já
  acabou, o clique passa pra próxima. Quando sobra borda escura dos dois lados
  da página (computador, celular deitado), as áreas que viram a página ocupam
  só a borda, pra o clique no mangá em si nunca virar a página sem querer. Manhwa/manhua e obras com a tag *Long Strip* abrem em rolagem
  contínua; o modo escolhido fica guardado separado pra tiras e pra páginas.
  Na rolagem, as barras somem ao descer e voltam ao subir.
- **iPhone com notch:** `viewport-fit=cover` e `env(safe-area-inset-*)`
  afastam barras e conteúdo do relógio e da barra de gestos.
- **App instalável (PWA):** manifest com ícones (inclusive o "maskable" que o
  Android recorta), atalhos (Continuar lendo, Buscar) e um service worker
  (`/sw.js`). No Chrome/Edge/Samsung Internet aparece "Instalar" (convite na
  página inicial e em "Sua conta"); no iPhone, a Nami explica o caminho
  (Compartilhar → Adicionar à Tela de Início).
- **O service worker não guarda páginas nem imagens:** as páginas mostram
  dados da conta e as imagens já têm o cache do navegador. Sem internet, ele
  mostra uma tela "sem conexão". Trade-off: não dá pra ler offline (seria um
  recurso grande, que ocupa espaço no celular).
- **Trade-offs:** instalar exige HTTPS (ou `localhost`): abrir pelo IP da rede
  (`http://192.168…`) não mostra "Instalar". No iPhone, o app instalado tem
  login separado do Safari (precisa entrar uma vez no app).

## Obras que só dá pra ler fora

Muitas obras licenciadas (ex.: Frieren, Dungeon Meshi) não têm nenhum capítulo
legível no MangaDex: os que sobraram são só links pro site oficial (MANGA Plus,
NamiComi, VIZ…). A busca do MangaDex não tem filtro pra isso (o
`hasAvailableChapters` não tira essas obras), então:

- cada obra que aparece numa listagem é verificada **em segundo plano**
  (`/manga/{id}/feed?limit=1&includeExternalUrl=0`), a no máximo metade do
  ritmo permitido, pra não atrasar quem está navegando; a resposta fica 12 h na
  memória, e abrir a página da obra já ensina de graça;
- a partir da visita seguinte, o cartão dessas obras ganha a faixa
  **"Só no site oficial"** e a capa fica mais apagada;
- na página da obra, um aviso diz que nenhum capítulo daquele idioma dá pra
  ler aqui e em quais sites eles estão; cada capítulo externo mostra o nome do
  site ("MANGA Plus ↗") em vez de "site oficial";
- "Começar a ler" vai pro primeiro capítulo legível, mesmo que seja em outro
  idioma ("Começar a ler · inglês").

## Autocompletar da busca

Depois de 3 letras e 300 ms sem digitar, `static/js/sugestoes.js` pede
`/busca/sugestoes` e mostra até 6 obras (a biblioteca local primeiro). A ordem
"por relevância" do MangaDex põe os derivados na frente ("one pi" trazia One
Piece Academy antes do One Piece), então as sugestões vêm das mais populares,
com as que têm o texto em algum título na frente. Setas escolhem, Enter abre,
Esc fecha (padrão "combobox" de acessibilidade). Limite próprio de 30 pedidos
por minuto por rede, porque cada pausa na digitação pode gastar uma consulta ao
MangaDex. No site normal nunca aparece obra adulta; na área madura o
autocompletar usa `/madura/busca/sugestoes` (o formulário diz o endereço em `data-sugestoes`).

## Obras por página

Seções, busca e biblioteca local mostram 30 obras por página; no fim da lista
dá pra escolher 30, 50, 80 ou 100 (o máximo que o MangaDex devolve de uma vez).
A escolha fica num cookie (`nami_por_pagina`), então vale pras próximas páginas
e visitas. Trade-off: com 100, a primeira visita a uma listagem demora mais pra
mostrar todas as capas (elas passam pelo limitador de 4/s do MangaDex).

## Proteções gerais (Fase 4)

- **Limite de requisições por IP** (`servicos/protecao.py`): 120 páginas e
  900 imagens por minuto, em "balde de fichas" (dá pra gastar um minuto inteiro
  de uma vez, mas não manter um ritmo maior). Acima disso: 429 com `Retry-After`.
  Ajustável por `NAMI_LIMITE_POR_MINUTO` e `NAMI_LIMITE_IMAGENS_POR_MINUTO`.
  Fica no app (e não no Caddy) porque o Caddy padrão não tem rate limit.
- **Capítulos novos:** no máximo 12 por minuto por rede (`/ler/`). Cada
  capítulo do MangaDex gasta uma das ~35 consultas por minuto que o servidor
  inteiro tem; sem isso, uma pessoa só travaria a leitura de todo mundo.
- **Tamanho dos envios:** 1 MB por requisição, menos no envio de .cbz/.cbr
  (`NAMI_UPLOAD_MAX_MB`). Acima disso: 413. O Caddy aplica os mesmos limites.
- **Cabeçalhos em toda resposta:** CSP (só scripts/estilos/imagens do próprio
  site; nenhum script inline), `X-Frame-Options: DENY`, `Referrer-Policy:
  same-origin`, `X-Content-Type-Options: nosniff`, `Cross-Origin-Opener-Policy`
  e `Cross-Origin-Resource-Policy` (outros sites não embutem as imagens da
  Nami), `Permissions-Policy` e HSTS com HTTPS. Sem CORS: nenhum outro site
  consegue chamar as rotas da Nami pelo navegador.
- **Erros:** página genérica "Algo deu errado", sem detalhes; o erro completo
  vai pro log do servidor. Sem `/docs` nem `/openapi.json`, e o uvicorn não
  diz o nome no cabeçalho `Server`.
- **Arquivos estáticos:** o endereço do CSS e dos scripts leva a versão do app
  e um resumo do conteúdo (`?v=0.6.0-1a2b3c4d`), então o navegador guarda por
  um ano e mesmo assim pega a versão nova depois de cada atualização. Os sem
  versão (logo, ícones) são conferidos a cada uso.
- **Fora dos buscadores:** `robots.txt` e `X-Robots-Tag: noindex`.
- **Docker:** usuário sem privilégios, um worker só, healthcheck no `/healthz`,
  a porta do app não fica exposta (só o Caddy/Cloudflare alcança). O container
  roda com o sistema de arquivos só leitura (grava só em `/data`; os
  temporários vão pra `/data/tmp`, no disco), sem nenhuma capability do Linux
  (`cap_drop: ALL`), com `no-new-privileges` e sem o token do túnel no ambiente.

## Identidade visual

A paleta vem da arte em `assets/nami band assets/`: azul-marinho de fundo
(`#0d182c`), azul da onda (`#2f8fe0`) e o creme do nome (`#f4ede1`). Os PNGs
originais têm fundo azul-marinho, que foi removido (transparente) pra encaixar
no site sem "quadrado" em volta. Os arquivos prontos estão em
`app/static/marca/`, junto com favicon e ícones de app (`icone-maskable-512.png`
é o ícone do app reduzido sobre fundo azul-marinho, pro recorte do Android).
O site é sempre escuro, como a marca. Os ícones da barra de baixo são SVG
desenhados direto no HTML (`templates/_icones.html`).

## Regras do MangaDex

Fonte: https://api.mangadex.org/docs/ (seções *Acceptable usage policy*,
*Limitations* e *Retrieving a chapter*).

- Creditar o MangaDex e o grupo de scan de cada capítulo. Sem anúncios nem cobrança.
- Atender pedidos de remoção de grupos de scan.
- User-Agent honesto (`config.user_agent`).
- ~5 req/s por IP no total (usamos 4/s) e 40/min no `/at-home/server` (usamos 35).
  Esse IP é o do servidor, **compartilhado por todos os usuários**; por isso
  há cache em memória (`app/cache.py`).
- Depois de um 429, parar até o horário do cabeçalho `X-RateLimit-Retry-After`.
  Insistir leva a ban temporário.
- Sem CORS pra outros sites e sem hotlink: tudo passa pelo servidor da Nami.
- Cada imagem baixada de um nó MangaDex@Home (URL que não é `mangadex.org`)
  precisa ser reportada em `https://api.mangadex.network/report`, com sucesso
  ou falha. Se falhar, pedir outro servidor e tentar de novo.
- `contentRating[]` sempre explícito; parâmetro desconhecido dá erro 400.
- `offset + limit` nunca acima de 10.000.

Comportamentos descobertos testando a API (out/2026):

- Capítulos removidos por DMCA ficam com `isUnavailable: true` e somem do
  feed. O filtro de busca "tem capítulos" não leva isso em conta, então obras
  populares (ex.: Frieren) aparecem na busca sem nenhum capítulo legível. A
  página da obra explica isso.
- Capítulos oficiais (ex.: MangaPlus, Netmarble) vêm com `externalUrl` e sem
  páginas; a Nami mostra um link pro site oficial.
- A capa principal de uma obra é a do volume mais recente (ex.: Bocchi the
  Rock! mostra o volume 8, com outra banda da história, não a protagonista).
  A Nami usa a mesma capa do MangaDex.

## Auditoria de segurança (out/2026)

Revisão completa feita na versão 0.6.0. O que foi conferido e o resultado:

| Item | Resultado |
|---|---|
| Chaves de API / segredos | A Nami não usa chave nenhuma (MangaDex e AniList são públicos). O único segredo é o token do túnel, que fica no `.env` (fora do git) e agora não chega ao container do app. |
| Variáveis de ambiente | Nenhuma senha tem valor padrão. `NAMI_COOKIE_SEGURO` vem ligado no Docker; com o cadastro aberto em produção, o log avisa. |
| Rotas de admin | Checagem no router inteiro (`dependencies=[Depends(exigir_admin)]`) e um teste que confere todas as rotas: visitante vai pro login, conta comum recebe 404. |
| Autenticação | argon2id, sessão com token aleatório (só o hash no banco), cookie HttpOnly/SameSite/Secure, limites por rede e por conta, senhas comuns recusadas, "sair dos outros aparelhos". |
| Acesso de cada usuário | Progresso, favoritos, histórico, reportes e tickets sempre filtrados pela conta logada; +18 checado também em cada imagem. |
| Formulários | Tamanho máximo em todo campo, validação no servidor, 1 MB por envio. SQL sempre parametrizado (SQLAlchemy). |
| XSS | Jinja escapa tudo (nenhum filtro `safe`), o JS usa `textContent` (nunca `innerHTML`), CSP sem script inline e links externos só `http(s)` (o `externalUrl` do MangaDex agora também é conferido). |
| Limite de requisições | Por rede (IPv6 por bloco /64), com memória limitada mesmo sob ataque de muitos IPs; limite próprio pra abrir capítulos. **Corrigido na 0.7:** atrás do NPM, o IP do visitante podia ser inventado (`--forwarded-allow-ips *`); agora só as redes internas informam o IP. |
| Endpoints JSON | Exigem login e checam permissão; CSRF barrado por `Sec-Fetch-Site`/`Origin`/`Referer`. |
| CORS | Desligado (nenhum `Access-Control-Allow-Origin`); há teste. |
| Cabeçalhos | CSP, HSTS, X-Frame-Options, nosniff, Referrer-Policy, COOP, CORP, Permissions-Policy. |
| Modo debug | Desligado: sem `/docs`, erro genérico sem detalhes, sem `--reload` no Docker, sem cabeçalho `Server`. |
| Dependências | Todas na versão mais recente; 41 pacotes conferidos no banco de vulnerabilidades OSV, nenhuma conhecida. |
| Pacotes sem uso | Saíram `websockets`, `PyYAML` e `watchfiles` (este ficou só no desenvolvimento). Todas as versões travadas em `constraints.txt`. |
| Arquivos expostos | Só `app/static` é servido; banco, biblioteca e `.env` ficam fora; ids de arquivo validados antes de virar caminho. |
| Banco | SQLite só no volume do Docker, sem porta de rede, usuário sem root; backup pelo comando `backup`. |
| Senhas | argon2id (RFC 9106) com re-hash automático quando os parâmetros mudam. |
| Segredos no git | Histórico inteiro varrido: nenhum `.env`, banco ou chave; só senhas falsas dos testes. |

O que ainda pode melhorar (decisões conscientes, não falhas):

- **Docker nunca rodou no Orange Pi:** as travas novas (`read_only`, `cap_drop`)
  só vão ser confirmadas no primeiro `docker compose up`.
- **Imagens de terceiros com tag móvel** (`caddy:2`, `cloudflared:latest`):
  recebem correções de segurança com `docker compose pull`, mas não são
  versões travadas.
- **Sem 2FA** (código no celular) no login, nem aviso por e-mail de login novo
  (a Nami não tem e-mail).
- **O cookie de sessão** poderia usar o prefixo `__Host-` (impede que um
  subdomínio grave cookie); com DuckDNS ou domínio próprio, o risco é baixo.

## Trade-offs que valem lembrar

- **Banda de upload:** toda página passa pela internet de casa duas vezes
  (entra e sai). A versão econômica (`data-saver`) tem ~10x menos bytes que a
  original (148 KB contra 1,5 MB numa página medida); é o padrão, e cada
  pessoa pode trocar no leitor.
- **Capas:** ficam no disco do servidor (`data/cache/capas`). Capa sem uso há
  5 dias é apagada (`NAMI_CAPAS_DIAS_SEM_USO`); cada vez que alguém vê, o prazo
  recomeça. O nome do arquivo leva a versão da capa, então quando o MangaDex
  troca a capa (volume novo) a nova é baixada e a velha apagada. A pasta nunca
  passa de `NAMI_CACHE_CAPAS_MB`. O navegador também guarda uma cópia por 1 dia,
  o que poupa upload do servidor. Na primeira visita as capas passam pelo
  limitador (4/s), então uma listagem nova demora alguns segundos pra completar.
- **Tudo síncrono** (`def`, não `async def`): atende menos acessos simultâneos
  que código assíncrono, o que não faz diferença pra poucos usuários, e é bem
  mais simples de ler e depurar.
- **Um processo só:** o cache, o limitador e os limites de tentativas vivem na
  memória do processo (reiniciar zera as contagens). Rodar vários workers do
  uvicorn multiplicaria as chamadas ao MangaDex, então o Docker usa um worker.
- **Caddy ou Cloudflare Tunnel:** o Caddy não depende de ninguém, mas exige
  abrir portas (impossível com CGNAT); o túnel funciona em qualquer rede, mas
  o tráfego passa pela Cloudflare. Detalhes em [DEPLOY.md](DEPLOY.md).
