<p align="center">
  <img src="assets/nami%20band%20assets/nami-logo.png" alt="Nami" width="220">
</p>

# Nami

Leitor self-hosted de mangás, manhwas e HQs. Feito pra rodar em casa (num
Orange Pi, por exemplo) e ser acessado pela internet.

A Nami não guarda scans: o catálogo e as páginas vêm da API oficial do
[MangaDex](https://mangadex.org), e a biblioteca local aceita só arquivos
.cbz/.cbr que você mesmo possui, enviados pelo painel de admin.

- **Leitor:** modo paginado ou rolagem contínua (manhwas já abrem em rolagem),
  navegação pelo teclado ou deslizando o dedo, direção mangá (direita→esquerda),
  qualidade econômica ou original.
- **Celular:** layout próprio, com barra de navegação embaixo, e dá pra
  instalar como app na tela inicial (Android e iPhone).
- **Contas:** continuar de onde parou, histórico, favoritos, idioma preferido.
- **Novidades:** o admin escreve posts sobre o que mudou no site, e quem tem
  conta vê uma bolinha no menu até ler.
- **Classificação etária:** o site normal nunca mostra conteúdo adulto
  (visitante vê só o livre, quem tem conta vê também o sugestivo). O adulto fica
  numa **área madura** separada, com tema preto, busca, histórico e favoritos
  próprios: entra quem confirmou a idade, digitando a senha da conta.
- **Leitura oficial:** com dados do [AniList](https://anilist.co), a página da
  obra avisa quando faltam capítulos (licenciamento, tradução parada) e mostra
  onde ler ou comprar oficialmente.
- **Biblioteca local:** envio de .cbz/.cbr, capa automática, metadados do
  ComicInfo.xml ou buscados no AniList ou no MangaDex.
- **Reportes e suporte:** quem tem conta avisa os admins de capa errada,
  capítulos faltando e afins, ou abre uma conversa (tipo chat) com o suporte.
- **Segurança:** senhas com argon2id, limites contra força bruta, proteção
  contra CSRF e XSS, cabeçalhos de segurança e container travado. A auditoria
  completa está na [arquitetura](docs/ARQUITETURA.md#auditoria-de-segurança-out2026).
- **Deploy:** Docker pra ARM64, HTTPS automático (Caddy) ou Cloudflare Tunnel.

Como tudo funciona por dentro: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).
Como colocar no ar: [docs/DEPLOY.md](docs/DEPLOY.md) (pelo terminal ou pelo
Portainer, com a imagem pronta `ghcr.io/vasconcelos39/nami`, que o GitHub monta
a cada atualização).

## Estado

- [x] **Fase 1:** busca e leitura via MangaDex, com filtro de classificação etária
- [x] **Fase 2:** contas, histórico, "continuar de onde parou", favoritos e opção +18 por conta
- [x] **Fase 3:** biblioteca local (.cbz/.cbr) e painel de admin (obras e usuários)
- [x] **Fase 4:** regras finais do +18, limite de requisições, cabeçalhos de segurança, Docker e guia de deploy
- [x] **Fase 5:** celular e app instalável, AniList (links oficiais e capítulos faltando), reportes, obras por página
- [x] **Fase 6:** suporte em forma de chat, auditoria de segurança, clique que rola no leitor e importação pelo terminal
- [x] **Fase 7:** autocompletar na busca, aviso de obra que só dá pra ler no site oficial, página por usuário no admin, verificação de idade e IP real atrás do proxy
- [x] **Fase 8:** área de Novidades, pra contar o que mudou no site
- [x] **Fase 9:** área madura separada (o site normal fica sem nada adulto) e Esc pra sair do capítulo

## Rodar no PC (Windows)

Precisa do Python 3.13. Na pasta do projeto:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Abra http://localhost:8000. O banco (`data/nami.db`) é criado sozinho na
primeira vez. Pra ter acesso ao painel de admin, crie a sua conta pelo site e
promova-a:

```powershell
.venv\Scripts\python -m app.cli promover SEU-NOME
```

Testes (não usam a internet, MangaDex e AniList são simulados):

```powershell
.venv\Scripts\python -m pytest
```

> Arquivos .cbr (RAR) precisam do programa `unar`, `unrar` ou 7-Zip instalado
> no PC. No Docker ele já vem. Arquivos .cbz funcionam sempre.

Pra adicionar uma pasta inteira de .cbz/.cbr de uma vez (ou arquivos grandes):

```powershell
.venv\Scripts\python -m app.cli importar "C:\caminho\da\pasta" --titulo "Nome da obra" --tipo manga
```

## Configuração

Tudo é opcional no PC. Copie `.env.example` para `.env` e ajuste: idiomas dos
capítulos (padrão: português, depois inglês), qualidade padrão das imagens,
cache de capas, tamanho máximo de envio, limites de requisição, cadastro
aberto ou fechado, duração do login e a consulta ao AniList. Cada opção está
explicada no arquivo.

## Atalhos do leitor

| Tecla | Ação |
|---|---|
| ← → ou A D | virar página (respeita a direção escolhida) |
| Espaço / Shift+Espaço | avançar / voltar (rola antes se a página for alta) |
| Home / End | primeira / última página |
| [ ] | capítulo anterior / próximo |
| M | alternar entre paginado e rolagem contínua |
| F | tela cheia |
| H | esconder as barras |
| C | configurações (modo, direção, tamanho, qualidade) |
| Esc | fecha as configurações; com elas fechadas, sai do capítulo |

No celular: deslize o dedo ou toque nas laterais pra virar a página, e toque
no meio pra esconder as barras. Na rolagem contínua, as barras somem sozinhas
ao descer.

Em "Clique na página" (nas configurações do leitor, ⚙), dá pra fazer o clique
em cima do mangá rolar a página um pouco pra baixo (pouco, meia tela ou quase
a tela toda) em vez de esconder as barras.

## Instalar no celular

Com a Nami aberta em HTTPS (como fica depois do [deploy](docs/DEPLOY.md)):

- **Android (Chrome, Edge, Samsung Internet):** toque em "Instalar" no convite
  da página inicial ou em "Sua conta", ou use "Instalar app" no menu do navegador.
- **iPhone (Safari):** toque em Compartilhar (o quadrado com a seta) e depois
  em "Adicionar à Tela de Início". No iPhone, o app tem login separado do
  Safari: entre na sua conta uma vez dentro do app.

## Créditos

Dados e imagens do catálogo: [MangaDex](https://mangadex.org). As traduções
são dos grupos de scan creditados em cada capítulo. A Nami não é afiliada ao
MangaDex e não exibe anúncios, como exigem os
[termos da API](https://api.mangadex.org/docs/).

Total de capítulos e links oficiais: [AniList](https://anilist.co), usado
de forma não comercial, como pedem os [termos deles](https://docs.anilist.co/guide/terms-of-use).

Licença: MIT.
