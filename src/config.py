"""Carregamento de configuração a partir de variáveis de ambiente / arquivo .env.

Não usamos python-dotenv para manter a ETAPA 1 com uma única dependência
externa (requests). O parser abaixo cobre o formato usual de .env:

    CHAVE=valor
    export CHAVE=valor
    CHAVE="valor com espaco"   # comentario
    # linha de comentario

Variáveis já presentes em os.environ têm precedência sobre o .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ENV_FILE = ".env"


class ConfigError(RuntimeError):
    """Configuração ausente ou inválida."""


def parse_env_file(path: str | Path) -> dict[str, str]:
    """Lê um arquivo .env e devolve um dicionário chave -> valor."""
    values: dict[str, str] = {}
    p = Path(path)
    if not p.is_file():
        return values

    for raw_line in p.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        else:
            # Comentário no fim da linha só vale fora de aspas.
            hash_pos = value.find(" #")
            if hash_pos != -1:
                value = value[:hash_pos].rstrip()
        if key:
            values[key] = value
    return values


def load_env(env_file: str | Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    """Combina o .env com o ambiente do processo (ambiente vence)."""
    merged = parse_env_file(env_file)
    merged.update({k: v for k, v in os.environ.items() if k in merged or k.startswith(("ZABBIX_", "OUTPUT_"))})
    return merged


def _as_bool(value: str, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "y", "on", "sim")


def _as_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_list(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


@dataclass(frozen=True)
class Settings:
    """Configuração efetiva da coleta."""

    url: str
    api_token: str = ""
    user: str = ""
    password: str = ""
    verify_tls: bool | str = True
    timeout: int = 30
    page_size: int = 500
    host_groups: list[str] = field(default_factory=list)
    output_dir: str = "output"

    @property
    def auth_mode(self) -> str:
        return "api_token" if self.api_token else "user_login"

    def describe(self) -> str:
        """Resumo seguro para log (nunca expõe token/senha)."""
        return (
            f"url={self.url} auth={self.auth_mode} verify_tls={self.verify_tls} "
            f"timeout={self.timeout}s page_size={self.page_size} "
            f"host_groups={self.host_groups or 'todos'}"
        )


def load_settings(env_file: str | Path = DEFAULT_ENV_FILE) -> Settings:
    """Monta Settings validando o mínimo necessário para a coleta."""
    env = load_env(env_file)

    url = (env.get("ZABBIX_URL") or "").strip()
    if not url:
        raise ConfigError(
            "ZABBIX_URL não definido. Copie .env.example para .env e preencha os dados "
            "do seu Zabbix (cp .env.example .env)."
        )

    api_token = (env.get("ZABBIX_API_TOKEN") or "").strip()
    user = (env.get("ZABBIX_USER") or "").strip()
    password = env.get("ZABBIX_PASSWORD") or ""

    if not api_token and not (user and password):
        raise ConfigError(
            "Nenhuma credencial encontrada. Defina ZABBIX_API_TOKEN (recomendado) "
            "ou ZABBIX_USER + ZABBIX_PASSWORD no .env."
        )

    verify_raw = (env.get("ZABBIX_VERIFY_TLS") or "true").strip()
    if verify_raw.lower() in ("1", "true", "yes", "on", "sim", ""):
        verify: bool | str = True
    elif verify_raw.lower() in ("0", "false", "no", "off", "nao", "não"):
        verify = False
    else:
        verify = verify_raw  # caminho para CA bundle

    return Settings(
        url=url,
        api_token=api_token,
        user=user,
        password=password,
        verify_tls=verify,
        timeout=_as_int(env.get("ZABBIX_TIMEOUT"), 30),
        page_size=_as_int(env.get("ZABBIX_PAGE_SIZE"), 500),
        host_groups=_as_list(env.get("ZABBIX_HOST_GROUPS")),
        output_dir=(env.get("OUTPUT_DIR") or "output").strip(),
    )
