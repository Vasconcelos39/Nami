<p align="center">
  <img src="assets/nami%20band%20assets/nami-logo.png" alt="Nami" width="220">
</p>

# Nami

Leitor self-hosted de mangás, manhwas e HQs. Feito pra rodar em casa (num
Orange Pi, por exemplo) e ser acessado pela internet.

A Nami não guarda scans: o catálogo e as páginas vêm da API oficial do
[MangaDex](https://mangadex.org), e a biblioteca local aceita só arquivos
.cbz/.cbr que você mesmo possui, enviados pelo painel de admin.

- **Leitor:** modo paginado ou rolagem contínua, navegação pelo teclado,
  direção mangá (direita→esquerda), qualidade econômica ou original.
- **Contas:** continuar de onde parou, histórico, favoritos, idioma preferido.
- **Classificação etária:** visitante vê só conteúdo livre, quem tem conta vê
  também o sugestivo, e o +18 só aparece pra quem ativa e confirma a maioridade.
- **Biblioteca local:** envio de .cbz/.cbr, capa automática, metadados do
  ComicInfo.xml ou buscados no MangaDex.
- **Deploy:** Docker pra ARM64, HTTPS automático (Caddy) ou Cloudflare Tunnel.

Como tudo funciona por dentro: [docs/ARQUITETURA.md](docs/ARQUITETURA.md).
Como colocar no ar: [docs/DEPLOY.md](docs/DEPLOY.md).

## Estado

- [x] **Fase 1:** busca e leitura via MangaDex, com filtro de classificação etária
- [x] **Fase 2:** contas, histórico, "continuar de onde parou", favoritos e opção +18 por conta
- [x] **Fase 3:** biblioteca local (.cbz/.cbr) e painel de admin (obras e usuários)
- [x] **Fase 4:** regras finais do +18, limite de requisições, cabeçalhos de segurança, Docker e guia de deploy

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

Testes (não usam a internet, o MangaDex é simulado):

```powershell
.venv\Scripts\python -m pytest
```

> Arquivos .cbr (RAR) precisam do programa `unar`, `unrar` ou 7-Zip instalado
> no PC. No Docker ele já vem. Arquivos .cbz funcionam sempre.

## Configuração

Tudo é opcional no PC. Copie `.env.example` para `.env` e ajuste: idiomas dos
capítulos (padrão: português, depois inglês), qualidade padrão das imagens,
cache de capas, tamanho máximo de envio, limites de requisição, cadastro
aberto ou fechado e duração do login. Cada opção está explicada no arquivo.

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

No celular: toque nas laterais pra virar a página e no meio pra esconder as barras.

## Créditos

Dados e imagens do catálogo: [MangaDex](https://mangadex.org). As traduções
são dos grupos de scan creditados em cada capítulo. A Nami não é afiliada ao
MangaDex e não exibe anúncios, como exigem os
[termos da API](https://api.mangadex.org/docs/).

Licença: MIT.
