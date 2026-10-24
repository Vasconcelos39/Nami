import io
import zipfile

import pytest
from PIL import Image

from app.servicos import biblioteca
from app.servicos.biblioteca import ErroDeImportacao, gerar_capa, importar_capitulo, inferir_numeros
from tests.ajudantes import cbz, imagem

OBRA = "a" * 32


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("One Piece v02 c015.cbz", ("15", "2")),
        ("Saga_012.cbz", ("12", None)),
        ("Berserk Vol. 3.cbz", (None, "3")),
        ("[Grupo] Obra - Cap 10.5 (2021).cbz", ("10.5", None)),
        ("Obra #7.cbr", ("7", None)),
        ("Chainsaw Man 12.cbz", ("12", None)),
        ("Vagabond 05.cbz", ("5", None)),
        ("Watchmen (1986).cbz", (None, None)),
    ],
)
def test_numeros_pelo_nome_do_arquivo(nome, esperado):
    assert inferir_numeros(nome) == esperado


def salvar(tmp_path, conteudo: bytes, nome="arquivo.cbz"):
    caminho = tmp_path / nome
    caminho.write_bytes(conteudo)
    return caminho


def test_importa_em_ordem_natural_e_ignora_o_que_nao_e_pagina(tmp_path):
    p1, p2, p10 = imagem((255, 0, 0), formato="JPEG"), imagem((0, 255, 0)), imagem((0, 0, 255))
    arquivo = salvar(
        tmp_path,
        cbz({
            "p10.png": p10,
            "p2.png": p2,
            "p1.jpg": p1,
            "__MACOSX/._p1.jpg": b"lixo do mac",
            ".DS_Store": b"lixo",
            "leiame.txt": b"texto",
            "falsa.jpg": b"isto nao e imagem",
            "../../fora.png": imagem(),
        }),
    )
    biblioteca_dir = tmp_path / "biblioteca"
    importado = importar_capitulo(arquivo, biblioteca_dir, OBRA)

    assert importado.total_paginas == 3
    pasta = biblioteca_dir / importado.pasta
    assert sorted(a.name for a in pasta.iterdir()) == ["0001.jpg", "0002.png", "0003.png"]
    assert (pasta / "0001.jpg").read_bytes() == p1
    assert (pasta / "0003.png").read_bytes() == p10  # "p10" depois de "p2"
    assert not (tmp_path / "fora.png").exists()
    assert importado.primeira_pagina == p1


def test_le_o_comicinfo(tmp_path):
    xml = """<?xml version="1.0"?>
    <ComicInfo>
      <Series>Minha Série</Series><Title>O começo</Title><Number>001</Number><Volume>2</Volume>
      <Writer>Fulana</Writer><Penciller>Beltrano</Penciller><Summary>Uma história.</Summary>
      <Genre>Ação, Aventura</Genre><Year>2019</Year><LanguageISO>pt</LanguageISO>
    </ComicInfo>"""
    importado = importar_capitulo(salvar(tmp_path, cbz({"1.png": imagem()}, xml)), tmp_path / "b", OBRA)
    info = importado.comicinfo
    assert (info.serie, info.titulo, info.numero, info.volume) == ("Minha Série", "O começo", "1", "2")
    assert info.autores == ["Fulana", "Beltrano"]
    assert info.tags == ["Ação", "Aventura"]
    assert info.ano == 2019


def test_imagem_bmp_vira_jpeg(tmp_path):
    importado = importar_capitulo(salvar(tmp_path, cbz({"1.bmp": imagem(formato="BMP")})), tmp_path / "b", OBRA)
    assert [a.name for a in (tmp_path / "b" / importado.pasta).iterdir()] == ["0001.jpg"]


def test_arquivo_que_nao_e_zip_nem_rar(tmp_path):
    with pytest.raises(ErroDeImportacao, match="não parece"):
        importar_capitulo(salvar(tmp_path, b"um texto qualquer"), tmp_path / "b", OBRA)


def test_zip_sem_imagens_nao_deixa_lixo(tmp_path):
    with pytest.raises(ErroDeImportacao, match="nenhuma imagem"):
        importar_capitulo(salvar(tmp_path, cbz({"leiame.txt": b"oi"})), tmp_path / "b", OBRA)
    assert list((tmp_path / "b" / OBRA).iterdir()) == []


def test_limite_de_paginas(tmp_path, monkeypatch):
    monkeypatch.setattr(biblioteca, "MAX_PAGINAS", 2)
    arquivo = salvar(tmp_path, cbz({f"{i}.png": imagem() for i in range(3)}))
    with pytest.raises(ErroDeImportacao, match="mais de 2"):
        importar_capitulo(arquivo, tmp_path / "b", OBRA)


def test_zip_com_senha(tmp_path, monkeypatch):
    arquivo = salvar(tmp_path, cbz({"1.png": imagem()}))
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("encrypted")))
    with pytest.raises(ErroDeImportacao, match="senha"):
        importar_capitulo(arquivo, tmp_path / "b", OBRA)


def test_cbr_e_aberto_pelo_rarfile(tmp_path, monkeypatch):
    # Sem o programa de RAR no PC, simulamos: o .cbr tem assinatura de RAR e o
    # "rarfile" devolve um ZIP (a interface dos dois é a mesma).
    zip_de_verdade = salvar(tmp_path, cbz({"1.png": imagem(), "2.png": imagem()}), "por-dentro.zip")
    cbr = salvar(tmp_path, b"Rar!\x1a\x07\x00" + b"\x00" * 32, "obra.cbr")
    monkeypatch.setattr(biblioteca, "_abrir_rar", lambda caminho: zipfile.ZipFile(zip_de_verdade))
    assert importar_capitulo(cbr, tmp_path / "b", OBRA).total_paginas == 2


def test_cbr_sem_programa_de_rar_explica_o_que_fazer(tmp_path, monkeypatch):
    import rarfile

    def sem_programa():
        raise rarfile.RarCannotExec("nenhum")

    monkeypatch.setattr(rarfile, "tool_setup", sem_programa)
    cbr = salvar(tmp_path, b"Rar!\x1a\x07\x00" + b"\x00" * 32, "obra.cbr")
    with pytest.raises(ErroDeImportacao, match="unar"):
        importar_capitulo(cbr, tmp_path / "b", OBRA)


def test_cbr_que_na_verdade_e_zip(tmp_path):
    arquivo = salvar(tmp_path, cbz({"1.png": imagem()}), "renomeado.cbr")
    assert importar_capitulo(arquivo, tmp_path / "b", OBRA).total_paginas == 1


def test_capa_de_webtoon_usa_so_o_topo(tmp_path):
    destino = tmp_path / "capa.jpg"
    gerar_capa(imagem(tamanho=(100, 2000)), destino)
    with Image.open(destino) as capa:
        assert capa.format == "JPEG"
        assert capa.height / capa.width == pytest.approx(1.5, abs=0.05)


def test_capa_invalida(tmp_path):
    with pytest.raises(ErroDeImportacao):
        gerar_capa(b"nao e imagem", tmp_path / "capa.jpg")


def test_imagem_falsa_e_recusada():
    assert biblioteca.normalizar_imagem(b"<svg onload=alert(1)>") is None
    dados = io.BytesIO()
    Image.new("RGB", (4, 4)).save(dados, "PNG")
    assert biblioteca.normalizar_imagem(dados.getvalue())[1] == ".png"
