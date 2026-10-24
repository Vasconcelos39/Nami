"""Respostas falsas no formato das APIs do MangaDex e do AniList, pra usar nos testes."""

API = "https://api.mangadex.org"
CAPAS = "https://uploads.mangadex.org/covers"
REPORT = "https://api.mangadex.network/report"
NO = "https://no-teste.mangadex.network"  # um nó MangaDex@Home de mentira
ANILIST = "https://graphql.anilist.co"
ANILIST_ID = 30013

OBRA = "11111111-1111-4111-8111-111111111111"
CAP1 = "22222222-2222-4222-8222-222222222221"
CAP2 = "22222222-2222-4222-8222-222222222222"
CAP3 = "22222222-2222-4222-8222-222222222223"


def manga(
    id=OBRA,
    titulo="Obra Teste",
    idioma="ja",
    classificacao="safe",
    capa="capa.jpg",
    descricao=None,
    alternativos=(),
    links=None,
    status="ongoing",
    ultimo_capitulo=None,
):
    relacoes = [{"id": "a0000000-0000-4000-8000-000000000000", "type": "author", "attributes": {"name": "Autora Teste"}}]
    if capa:
        relacoes.append({"id": "c0000000-0000-4000-8000-000000000000", "type": "cover_art", "attributes": {"fileName": capa}})
    return {
        "id": id,
        "type": "manga",
        "attributes": {
            "title": {"en": titulo},
            "altTitles": list(alternativos),
            "description": descricao or {"en": "Uma descrição."},
            "links": links,
            "originalLanguage": idioma,
            "lastChapter": ultimo_capitulo,
            "contentRating": classificacao,
            "status": status,
            "year": 2020,
            "tags": [{"id": "t", "type": "tag", "attributes": {"name": {"en": "Action"}}}],
        },
        "relationships": relacoes,
    }


def media_anilist(id=ANILIST_ID, capitulos=None, status="RELEASING", links=None, adulto=False, generos=("Action",)):
    """Um "Media" do AniList, no formato que a consulta da Nami pede."""
    return {
        "id": id,
        "siteUrl": f"https://anilist.co/manga/{id}",
        "format": "MANGA",
        "status": status,
        "chapters": capitulos,
        "volumes": None,
        "countryOfOrigin": "JP",
        "isAdult": adulto,
        "title": {"romaji": "Obra Teste", "english": "Test Work", "native": "テスト"},
        "synonyms": [],
        "startDate": {"year": 2019},
        "description": "Primeira linha.<br><br>Segunda <i>linha</i> &amp; fim.",
        "genres": list(generos),
        "externalLinks": links
        if links is not None
        else [
            {"url": "https://mangaplus.shueisha.co.jp/titles/1", "site": "MANGA Plus", "type": "STREAMING", "language": "English", "isDisabled": False},
            {"url": "https://editora.example.com.br/obra", "site": "Editora BR", "type": "INFO", "language": "Portuguese", "isDisabled": False},
            {"url": "https://twitter.com/obra", "site": "Twitter", "type": "SOCIAL", "language": None, "isDisabled": False},
            {"url": "https://fechado.example/obra", "site": "Fechado", "type": "STREAMING", "language": "Japanese", "isDisabled": True},
        ],
        "staff": {
            "edges": [
                {"role": "Story & Art", "node": {"name": {"full": "Autora Teste"}}},
                {"role": "Translator (English)", "node": {"name": {"full": "Tradutor"}}},
            ]
        },
    }


def resposta_anilist(media=None):
    return {"data": {"Media": media if media is not None else media_anilist()}}


def lista(*mangas, total=None):
    return {"result": "ok", "data": list(mangas), "total": len(mangas) if total is None else total}


def capitulo(id=CAP1, obra=OBRA, numero="1", idioma="pt-br", grupo="Grupo Teste", paginas=3, externo=None, manga_attrs=None):
    relacoes = []
    if grupo:
        relacoes.append({"id": "g0000000-0000-4000-8000-000000000000", "type": "scanlation_group", "attributes": {"name": grupo}})
    relacao_manga = {"id": obra, "type": "manga"}
    if manga_attrs is not None:
        relacao_manga["attributes"] = manga_attrs
    relacoes.append(relacao_manga)
    return {
        "id": id,
        "type": "chapter",
        "attributes": {
            "volume": None,
            "chapter": numero,
            "title": None,
            "translatedLanguage": idioma,
            "externalUrl": externo,
            "isUnavailable": False,
            "publishAt": "2024-06-14T09:17:29+00:00",
            "pages": paginas,
        },
        "relationships": relacoes,
    }


def capitulo_detalhe(id=CAP1, classificacao="safe", **kwargs):
    """Resposta de /chapter/{id}?includes[]=manga (vem com os dados da obra)."""
    return {"result": "ok", "data": capitulo(id, manga_attrs=manga(classificacao=classificacao)["attributes"], **kwargs)}


def feed(*capitulos):
    return {"result": "ok", "data": list(capitulos), "total": len(capitulos)}


def servidor(base=NO, hash="abc123", paginas=3):
    return {
        "result": "ok",
        "baseUrl": base,
        "chapter": {
            "hash": hash,
            "data": [f"{n}-original.jpg" for n in range(1, paginas + 1)],
            "dataSaver": [f"{n}-leve.jpg" for n in range(1, paginas + 1)],
        },
    }
