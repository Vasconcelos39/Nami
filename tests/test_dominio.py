from app.dominio import Capitulo, navegacao


def cap(id, numero, grupo="A", idioma="pt-br", externo=None):
    return Capitulo(fonte="mangadex", id=id, obra_id="o", idioma=idioma, numero=numero, grupos=(grupo,), link_externo=externo)


def test_navegacao_segue_o_mesmo_grupo():
    capitulos = [cap("1a", "1"), cap("2b", "2", "B"), cap("2a", "2"), cap("3b", "3", "B"), cap("2en", "2", idioma="en")]

    lista, anterior, proximo = navegacao(capitulos, capitulos[0])
    assert [c.id for c in lista] == ["1a", "2a", "3b"]  # um por número, só pt-br
    assert anterior is None
    assert proximo.id == "2a"

    _, anterior, proximo = navegacao(capitulos, capitulos[2])
    assert anterior.id == "1a"
    assert proximo.id == "3b"  # o grupo A não tem o 3: cai pro B


def test_navegacao_pula_capitulos_externos_e_ordena_decimais():
    capitulos = [cap("10", "10"), cap("10.5", "10.5"), cap("11", "11", externo="https://oficial"), cap("12", "12")]
    lista, _, proximo = navegacao(capitulos, capitulos[1])
    assert [c.id for c in lista] == ["10", "10.5", "12"]
    assert proximo.id == "12"
