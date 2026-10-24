"""Configurações da Nami.

Lidas de variáveis de ambiente que começam com NAMI_ (ou do arquivo .env na
raiz do projeto). Exemplo: NAMI_DATA_DIR=/data
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

RAIZ_PROJETO = Path(__file__).resolve().parent.parent


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NAMI_", env_file=RAIZ_PROJETO / ".env", extra="ignore"
    )

    # Pasta com o banco, a biblioteca local e o cache de capas.
    data_dir: Path = RAIZ_PROJETO / "data"

    # Idiomas dos capítulos, em ordem de preferência.
    idiomas: list[str] = ["pt-br", "en"]

    # "data-saver" = imagens comprimidas (bem menores, poupam sua banda de upload).
    # "data" = qualidade original. O leitor deixa cada pessoa trocar.
    qualidade_padrao: Literal["data-saver", "data"] = "data-saver"

    # Cache de capas no disco: capa sem uso há esse número de dias é apagada,
    # e a pasta nunca passa do tamanho máximo.
    capas_dias_sem_uso: int = 5
    cache_capas_mb: int = 200

    # Biblioteca local: tamanho máximo de cada arquivo .cbz/.cbr enviado pelo admin.
    upload_max_mb: int = 1024

    # Limite de requisições por IP, por minuto (0 = sem limite). Imagens têm um
    # limite separado e maior porque o leitor baixa várias páginas de uma vez.
    limite_por_minuto: int = 120
    limite_imagens_por_minuto: int = 900

    # Contas
    cadastro_aberto: bool = True  # False = ninguém novo consegue criar conta
    sessao_dias: int = 30  # quanto tempo um login dura
    # True quando o site estiver atrás de HTTPS (Fase 4): o cookie de login só
    # trafega criptografado. Em desenvolvimento (http://localhost) fica False.
    cookie_seguro: bool = False

    mangadex_api: str = "https://api.mangadex.org"
    mangadex_capas: str = "https://uploads.mangadex.org/covers"
    mangadex_report: str = "https://api.mangadex.network/report"
    # AniList: total de capítulos da obra original e onde ler oficialmente.
    # false desliga (a página da obra só deixa de mostrar essas informações).
    anilist_ativo: bool = True
    anilist_api: str = "https://graphql.anilist.co"
    # O MangaDex exige um User-Agent honesto, que identifique o app.
    user_agent: str = f"Nami/{__version__} (+https://github.com/vasconcelos39/nami)"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.data_dir / 'nami.db').as_posix()}"

    @property
    def dir_cache_capas(self) -> Path:
        return self.data_dir / "cache" / "capas"

    @property
    def dir_biblioteca(self) -> Path:
        return self.data_dir / "biblioteca"

    @property
    def dir_temporario(self) -> Path:
        return self.data_dir / "tmp"


@lru_cache
def get_config() -> Config:
    return Config()
