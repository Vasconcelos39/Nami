from dataclasses import replace
from datetime import UTC, datetime

from app.catalogos.anilist import _converter
from app.dominio import Capitulo, Classificacao, LinkOficial, Obra, Tipo, juntar_links
from app.servicos.cobertura import analisar
from tests.fabrica import media_anilist

AGORA = datetime(2026, 10, 1, tzinfo=UTC)
OBRA = Obra(fonte="mangadex", id="x", titulo="X", tipo=Tipo.MANGA, classificacao=Classificacao.SAFE, status="ongoing")


def caps(idioma, *numeros, publicado=datetime(2026, 9, 1, tzinfo=UTC)):
    return [
        Capitulo(fonte="mangadex", id=f"{idioma}-{n}", obra_id="x", idioma=idioma, numero=str(n), publicado_em=publicado)
        for n in numeros
    ]


def ficha(**kwargs):
    return _converter(media_anilist(**kwargs))


def test_avisa_quando_a_obra_original_tem_mais_capitulos():
    resumo = analisar(OBRA, {"pt-br": caps("pt-br", 1, 2, 3)}, "pt-br", ficha(capitulos=10, status="FINISHED"), agora=AGORA)
    assert resumo.faltando
    assert (resumo.ultimo_aqui, resumo.total_original, resumo.referencia) == (3, 10, "AniList")


def test_obra_completa_aqui_nao_tem_aviso():
    resumo = analisar(OBRA, {"pt-br": caps("pt-br", 1, 2)}, "pt-br", ficha(capitulos=2, status="FINISHED"), agora=AGORA)
    assert not resumo.tem_aviso


def test_sem_total_no_anilist_usa_o_ultimo_capitulo_do_mangadex():
    obra = replace(OBRA, ultimo_capitulo="5", status="completed")
    resumo = analisar(obra, {"pt-br": caps("pt-br", 1, 2)}, "pt-br", None, agora=AGORA)
    assert resumo.faltando and resumo.referencia == "MangaDex"


def test_aponta_o_idioma_que_vai_mais_longe():
    por_idioma = {"pt-br": caps("pt-br", 1, 2), "en": caps("en", *range(1, 41))}
    resumo = analisar(OBRA, por_idioma, "pt-br", None, agora=AGORA)
    assert resumo.mais_longe == ("en", 40)
    assert analisar(OBRA, por_idioma, "en", None, agora=AGORA).mais_longe is None


def test_traducao_parada_ha_mais_de_um_ano():
    antigos = caps("pt-br", 1, 2, publicado=datetime(2020, 7, 4, tzinfo=UTC))
    resumo = analisar(OBRA, {"pt-br": antigos}, "pt-br", None, agora=AGORA)
    assert resumo.parada_desde == datetime(2020, 7, 4, tzinfo=UTC)
    # Obra já terminada: capítulo antigo é normal.
    assert analisar(replace(OBRA, status="completed"), {"pt-br": antigos}, "pt-br", None, agora=AGORA).parada_desde is None


def test_datas_sem_fuso_da_biblioteca_local():
    antigos = caps("pt-br", 1, publicado=datetime(2020, 1, 1))  # sem fuso, como no SQLite
    assert analisar(OBRA, {"pt-br": antigos}, "pt-br", None, agora=AGORA).parada_desde is not None


def test_biblioteca_so_com_volumes_compara_volumes():
    volumes = [Capitulo(fonte="local", id=f"v{n}", obra_id="x", idioma="pt-br", volume=str(n)) for n in (1, 2)]
    media = media_anilist(capitulos=50)
    media["volumes"] = 8
    resumo = analisar(OBRA, {"pt-br": volumes}, "pt-br", _converter(media), agora=AGORA)
    assert (resumo.unidade, resumo.ultimo_aqui, resumo.total_original) == ("vol", 2, 8)


def test_links_juntam_mangadex_e_anilist_sem_repetir():
    obra = replace(OBRA, links_oficiais=(LinkOficial("MANGA Plus", "https://mangaplus.shueisha.co.jp/titles/1/", "en"),))
    resumo = analisar(obra, {}, None, ficha(), idiomas_preferidos=["pt-br", "en"], agora=AGORA)
    assert [link.site for link in resumo.links] == ["MANGA Plus", "Editora BR"]  # leitura antes de loja


def test_ordem_dos_links_segue_os_idiomas_da_pessoa():
    links = juntar_links(
        [
            LinkOficial("JP", "https://jp.example", "ja"),
            LinkOficial("BR", "https://br.example", "pt-br"),
            LinkOficial("Loja", "https://loja.example", "pt-br", leitura=False),
            LinkOficial("EN", "https://en.example", "en"),
        ],
        idiomas_primeiro=["pt-br", "en", "ja"],
    )
    assert [link.site for link in links] == ["BR", "EN", "JP", "Loja"]
