"""Respostas falsas no formato da API do MangaDex, pra usar nos testes."""

API = "https://api.mangadex.org"
CAPAS = "https://uploads.mangadex.org/covers"
REPORT = "https://api.mangadex.network/report"
NO = "https://no-teste.mangadex.network"  # um nó MangaDex@Home de mentira

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
            "originalLanguage": idioma,
            "contentRating": classificacao,
            "status": "ongoing",
            "year": 2020,
            "tags": [{"id": "t", "type": "tag", "attributes": {"name": {"en": "Action"}}}],
        },
        "relationships": relacoes,
    }


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
