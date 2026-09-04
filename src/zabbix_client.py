"""Cliente Zabbix JSON-RPC estritamente READ-ONLY.

Garantias de segurança desta camada:

* Existe uma allowlist fechada de métodos (`ALLOWED_METHODS`). Qualquer outro
  método levanta `ReadOnlyViolationError` **antes** de qualquer requisição HTTP.
* Nenhum método de escrita (`*.create`, `*.update`, `*.delete`, `*.massadd`,
  `*.massupdate`, `*.massremove`, `*.import`, `*.acknowledge`) existe no código
  nem é alcançável pela allowlist.
* `user.login` / `user.logout` só são liberados quando a autenticação por
  usuário/senha é usada (fallback). Elas não alteram dados de monitoramento,
  apenas abrem/encerram uma sessão. Com API token elas ficam bloqueadas.

Autenticação:
* Zabbix >= 6.4 / 7.x  -> header `Authorization: Bearer <token|sessionid>`
* Zabbix <= 6.2        -> propriedade `auth` no corpo do JSON-RPC
* `apiinfo.version` é sempre chamado sem autenticação (exigência da API).
Se o modo escolhido falhar por erro de autorização, o cliente tenta o outro
modo uma única vez (compatibilidade entre versões).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Iterable, Iterator, Sequence

from .config import Settings

logger = logging.getLogger(__name__)

#: Métodos permitidos. Allowlist fechada — é isto que garante o read-only.
ALLOWED_METHODS: frozenset[str] = frozenset(
    {
        "apiinfo.version",
        "trigger.get",
        "host.get",
        "hostgroup.get",
        "template.get",
        "item.get",
        "triggerprototype.get",
    }
)

#: Métodos de sessão (não alteram dados). Liberados apenas no fallback usuário/senha.
SESSION_METHODS: frozenset[str] = frozenset({"user.login", "user.logout"})

#: Sufixos de escrita — usados apenas para produzir uma mensagem de erro clara.
WRITE_SUFFIXES: tuple[str, ...] = (
    ".create",
    ".update",
    ".delete",
    ".massadd",
    ".massupdate",
    ".massremove",
    ".import",
    ".acknowledge",
    ".copy",
    ".replacehostinterfaces",
)

#: Erros da API que indicam problema de autenticação/autorização.
_AUTH_ERROR_HINTS = ("not authorised", "not authorized", "re-login", "session terminated", "invalid parameter \"/auth\"")


class ZabbixError(RuntimeError):
    """Erro devolvido pela API do Zabbix ou pelo transporte HTTP."""


class ReadOnlyViolationError(ZabbixError):
    """Tentativa de chamar um método que não pertence à allowlist de leitura."""


class ZabbixAuthError(ZabbixError):
    """Falha de autenticação/autorização."""


def api_endpoint(url: str) -> str:
    """Normaliza a URL base para o endpoint JSON-RPC."""
    url = (url or "").strip().rstrip("/")
    if url.endswith("api_jsonrpc.php"):
        return url
    return f"{url}/api_jsonrpc.php"


def parse_version(version: str) -> tuple[int, ...]:
    """'7.0.5' -> (7, 0, 5). Partes não numéricas são ignoradas."""
    parts: list[int] = []
    for chunk in str(version or "").split("."):
        digits = ""
        for ch in chunk:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits == "":
            break
        parts.append(int(digits))
    return tuple(parts) or (0,)


def chunked(items: Sequence[Any], size: int) -> Iterator[list[Any]]:
    """Divide uma sequência em lotes (para consultas por listas de IDs)."""
    size = max(1, int(size))
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


class RequestsTransport:
    """Transporte HTTP padrão (requests). Isolado para permitir testes offline."""

    def __init__(self, endpoint: str, timeout: int = 30, verify: bool | str = True):
        try:
            import requests  # import tardio: mantém o módulo testável sem a dependência
        except ImportError as exc:  # pragma: no cover
            raise ZabbixError(
                "A biblioteca 'requests' não está instalada. Rode: pip install -r requirements.txt"
            ) from exc
        self._requests = requests
        self.endpoint = endpoint
        self.timeout = timeout
        self.verify = verify
        self.session = requests.Session()
        self.session.headers.update(
            {"Content-Type": "application/json-rpc", "User-Agent": "zabbix-alert-knowledge/0.1 (read-only)"}
        )

    def __call__(self, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        try:
            response = self.session.post(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                timeout=self.timeout,
                verify=self.verify,
            )
        except self._requests.exceptions.SSLError as exc:
            raise ZabbixError(
                f"Falha de TLS ao acessar {self.endpoint}: {exc}. "
                "Se o certificado for interno, aponte ZABBIX_VERIFY_TLS para o CA bundle."
            ) from exc
        except self._requests.exceptions.RequestException as exc:
            raise ZabbixError(f"Falha de rede ao acessar {self.endpoint}: {exc}") from exc

        if response.status_code >= 400:
            raise ZabbixError(
                f"HTTP {response.status_code} em {self.endpoint}: {response.text[:300]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ZabbixError(
                f"Resposta não-JSON de {self.endpoint} (HTTP {response.status_code}): {response.text[:300]}"
            ) from exc


class ZabbixReadOnlyClient:
    """Cliente de leitura da API do Zabbix."""

    def __init__(
        self,
        url: str,
        api_token: str = "",
        user: str = "",
        password: str = "",
        timeout: int = 30,
        verify_tls: bool | str = True,
        page_size: int = 500,
        trigger_batch_size: int = 50,
        transport: Callable[[dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
    ):
        self.endpoint = api_endpoint(url)
        self._api_token = api_token
        self._user = user
        self._password = password
        self.page_size = page_size
        #: hosts por chamada trigger.get na coleta completa. Menor que page_size
        #: de propósito: trigger.get com todos os selects usados aqui é uma
        #: consulta pesada por host — um lote grande demais pode devolver HTTP
        #: 500 (timeout/memória) no servidor Zabbix.
        self.trigger_batch_size = max(1, trigger_batch_size)
        self._transport = transport or RequestsTransport(self.endpoint, timeout=timeout, verify=verify_tls)

        self._request_id = 0
        self._session_id: str = ""
        self._logged_in = False
        self._version: str = ""
        self._auth_style: str = ""  # "bearer" | "auth_field"
        self.call_log: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ fábrica
    @classmethod
    def from_settings(cls, settings: Settings, transport: Any | None = None) -> "ZabbixReadOnlyClient":
        return cls(
            url=settings.url,
            api_token=settings.api_token,
            user=settings.user,
            password=settings.password,
            timeout=settings.timeout,
            verify_tls=settings.verify_tls,
            page_size=settings.page_size,
            trigger_batch_size=settings.trigger_batch_size,
            transport=transport,
        )

    # ----------------------------------------------------------------- guardião
    def _assert_read_only(self, method: str) -> None:
        if method in ALLOWED_METHODS:
            return
        if method in SESSION_METHODS and not self._api_token:
            return
        if method.endswith(WRITE_SUFFIXES):
            raise ReadOnlyViolationError(
                f"Método de escrita '{method}' bloqueado: esta integração é somente leitura."
            )
        raise ReadOnlyViolationError(
            f"Método '{method}' não está na allowlist de leitura "
            f"({', '.join(sorted(ALLOWED_METHODS))})."
        )

    # ------------------------------------------------------------------- request
    def call(self, method: str, params: Any = None, *, authenticated: bool = True) -> Any:
        """Executa uma chamada JSON-RPC de leitura."""
        self._assert_read_only(method)

        self._request_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": {} if params is None else params,
            "id": self._request_id,
        }
        headers: dict[str, str] = {"Content-Type": "application/json-rpc"}

        credential = self._credential()
        if authenticated and credential:
            if self._auth_style == "bearer":
                headers["Authorization"] = f"Bearer {credential}"
            else:
                payload["auth"] = credential

        result = self._send(payload, headers, method)

        # Compatibilidade: se o estilo de autenticação escolhido não serviu,
        # tenta o outro uma única vez.
        if isinstance(result, ZabbixAuthError) and authenticated and credential:
            other = "auth_field" if self._auth_style == "bearer" else "bearer"
            logger.debug("Autenticação via %s falhou; tentando %s", self._auth_style, other)
            self._auth_style = other
            payload.pop("auth", None)
            headers.pop("Authorization", None)
            if other == "bearer":
                headers["Authorization"] = f"Bearer {credential}"
            else:
                payload["auth"] = credential
            result = self._send(payload, headers, method)

        if isinstance(result, ZabbixError):
            raise result
        return result

    def _send(self, payload: dict[str, Any], headers: dict[str, str], method: str) -> Any:
        body = self._transport(payload, headers)
        params = payload.get("params")
        self.call_log.append(
            {
                "method": method,
                "params": self._sanitize_params(params),
                "ok": "error" not in body,
            }
        )
        if "error" in body:
            error = body["error"] or {}
            message = f"{error.get('message', 'Erro da API')}: {error.get('data', '')}".strip()
            lowered = message.lower()
            if any(hint in lowered for hint in _AUTH_ERROR_HINTS):
                return ZabbixAuthError(f"{method} -> {message}")
            return ZabbixError(f"{method} -> {message}")
        result = body.get("result")
        if isinstance(result, list):
            self.call_log[-1]["result_count"] = len(result)
        return result

    @staticmethod
    def _sanitize_params(params: Any) -> Any:
        """Nunca registrar credenciais no log de chamadas do snapshot."""
        if not isinstance(params, dict):
            return params
        safe = {}
        for key, value in params.items():
            if key in ("password", "user", "username", "token", "auth"):
                safe[key] = "***"
            elif isinstance(value, list) and len(value) > 12:
                safe[key] = f"<{len(value)} itens>"
            else:
                safe[key] = value
        return safe

    def _credential(self) -> str:
        return self._api_token or self._session_id

    # ---------------------------------------------------------------- sessão/API
    def api_version(self) -> str:
        """Versão da API (chamada sem autenticação, como exige o Zabbix)."""
        if not self._version:
            self._version = str(self.call("apiinfo.version", {}, authenticated=False))
        return self._version

    def connect(self) -> str:
        """Descobre a versão, define o estilo de autenticação e valida o acesso."""
        version = self.api_version()
        self._auth_style = "bearer" if parse_version(version) >= (6, 4) else "auth_field"

        if not self._api_token:
            if not (self._user and self._password):
                raise ZabbixAuthError("Sem API token e sem usuário/senha configurados.")
            # user.login não altera dados; abre apenas uma sessão de leitura.
            self._session_id = str(
                self.call("user.login", {"username": self._user, "password": self._password}, authenticated=False)
            )
            self._logged_in = True

        # Valida credencial com a consulta mais barata possível.
        self.call("hostgroup.get", {"countOutput": True, "limit": 1})
        return version

    def logout(self) -> None:
        if self._logged_in and self._session_id:
            try:
                self.call("user.logout", {})
            except ZabbixError as exc:  # pragma: no cover - best effort
                logger.debug("Falha ao encerrar sessão: %s", exc)
            finally:
                self._logged_in = False
                self._session_id = ""

    def __enter__(self) -> "ZabbixReadOnlyClient":
        self.connect()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.logout()

    # ------------------------------------------------------------------ helpers
    @property
    def version(self) -> str:
        return self._version

    @property
    def auth_style(self) -> str:
        return self._auth_style

    @property
    def auth_description(self) -> str:
        mode = "api_token" if self._api_token else "user_login"
        return f"{mode} ({'Authorization: Bearer' if self._auth_style == 'bearer' else 'campo auth'})"

    def supports_host_groups_select(self) -> bool:
        """`selectHostGroups` existe a partir do Zabbix 6.2 (antes: `selectGroups`)."""
        return parse_version(self.api_version()) >= (6, 2)

    def get_by_ids(self, method: str, id_field: str, ids: Iterable[str], params: dict[str, Any]) -> list[dict[str, Any]]:
        """Executa `method` em lotes para uma lista de IDs, concatenando resultados."""
        unique = sorted({str(i) for i in ids if str(i) not in ("", "0")})
        collected: list[dict[str, Any]] = []
        for batch in chunked(unique, self.page_size):
            call_params = dict(params)
            call_params[id_field] = batch
            result = self.call(method, call_params) or []
            collected.extend(result)
        return collected
