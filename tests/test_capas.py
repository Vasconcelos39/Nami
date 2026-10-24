import os
import time

import pytest

from app.dominio import Imagem
from app.servicos.imagens import CacheCapas

OBRA = "obra-1"
DIA = 24 * 3600


class FonteFalsa:
    id = "falsa"

    def __init__(self):
        self.versao = "capa-v1.jpg"
        self.downloads = 0

    def versao_capa(self, obra_id):
        return self.versao

    def imagem_capa(self, obra_id):
        self.downloads += 1
        return Imagem(f"bytes de {self.versao}".encode(), "image/jpeg")


@pytest.fixture
def fonte():
    return FonteFalsa()


@pytest.fixture
def cache(tmp_path):
    return CacheCapas(tmp_path, limite_mb=1, dias_sem_uso=5)


def arquivos(cache):
    return sorted(cache.pasta.rglob("*.jpg"))


def envelhecer(arquivo, dias):
    antes = time.time() - dias * DIA
    os.utime(arquivo, (antes, antes))


def test_segunda_vez_vem_do_disco(cache, fonte):
    cache.obter(fonte, OBRA)
    assert cache.obter(fonte, OBRA).conteudo == b"bytes de capa-v1.jpg"
    assert fonte.downloads == 1


def test_capa_sem_uso_ha_mais_de_5_dias_e_apagada(cache, fonte):
    cache.obter(fonte, OBRA)
    envelhecer(arquivos(cache)[0], 6)
    cache.limpar()
    assert arquivos(cache) == []


def test_usar_a_capa_renova_o_prazo(cache, fonte):
    cache.obter(fonte, OBRA)
    envelhecer(arquivos(cache)[0], 4)
    cache.obter(fonte, OBRA)  # alguém viu a capa: o prazo recomeça
    ultimo_uso = arquivos(cache)[0].stat().st_mtime
    assert time.time() - ultimo_uso < 60
    cache.limpar()
    assert len(arquivos(cache)) == 1


def test_capa_nova_substitui_a_velha(cache, fonte):
    cache.obter(fonte, OBRA)
    fonte.versao = "capa-v2.jpg"  # a fonte trocou a capa (volume novo)
    assert cache.obter(fonte, OBRA).conteudo == b"bytes de capa-v2.jpg"
    assert fonte.downloads == 2
    assert len(arquivos(cache)) == 1


def test_versao_desconhecida_usa_a_do_disco(cache, fonte):
    cache.obter(fonte, OBRA)
    fonte.versao = None  # ex.: o servidor reiniciou e ainda não viu essa obra numa busca
    cache.obter(fonte, OBRA)
    assert fonte.downloads == 1


def test_limite_de_tamanho_tira_as_usadas_ha_mais_tempo(tmp_path, fonte):
    cache = CacheCapas(tmp_path, limite_mb=0, dias_sem_uso=5)
    cache.obter(fonte, "antiga")
    cache.obter(fonte, "nova")
    antiga, nova = sorted(cache.pasta.rglob("*.jpg"), key=lambda a: a.name)
    envelhecer(antiga, 1)
    cache.limite_bytes = nova.stat().st_size  # cabe só uma
    cache.limpar()
    assert not antiga.exists()
    assert nova.exists()


def test_id_com_caracteres_estranhos_nao_vira_arquivo(cache, fonte):
    cache.obter(fonte, "../fora")
    assert arquivos(cache) == []
    assert fonte.downloads == 1
