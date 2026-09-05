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
import time
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


class ZabbixTransientError(ZabbixError):
    """Falha provavelmente temporária: vale a pena tentar de novo.

    O caso que motivou esta classe é o HTTP 500 de corpo vazio que o Zabbix
    devolve quando a consulta estoura tempo ou memória do servidor. Não é um
    erro de dados nem de permissão: a mesma consulta, menor, funciona.
    """

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


#: Status HTTP que valem retry (item 5 da Fase 2).
TRANSIENT_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504, 507, 509})

#: Trechos de mensagem da API que indicam sobrecarga/timeout, não erro de dados.
_TRANSIENT_HINTS = (
    "timeout",
    "timed out",
    "gone away",
    "too many connections",
    "connection reset",
    "temporarily unavailable",
    "out of memory",
    "allowed memory size",
    "maximum execution time",
)


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
        except (self._requests.exceptions.Timeout, self._requests.exceptions.ConnectionError) as exc:
            # Timeout/conexão derrubada: o servidor pode estar apenas ocupado.
            raise ZabbixTransientError(f"Falha de rede ao acessar {self.endpoint}: {exc}") from exc
        except self._requests.exceptions.RequestException as exc:
            raise ZabbixError(f"Falha de rede ao acessar {self.endpoint}: {exc}") from exc

        if response.status_code in TRANSIENT_STATUS:
            corpo = (response.text or "").strip()[:300] or "(corpo vazio)"
            raise ZabbixTransientError(
                f"HTTP {response.status_code} em {self.endpoint}: {corpo}",
                status=response.status_code,
            )
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
        max_retries: int = 4,
        retry_backoff: float = 2.0,
        retry_backoff_max: float = 30.0,
        min_page_size: int = 25,
        transport: Callable[[dict[str, Any], dict[str, str]], dict[str, Any]] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.endpoint = api_endpoint(url)
        self._api_token = api_token
        self._user = user
        self._password = password
        self.page_size = max(1, int(page_size))
        #: hosts por chamada trigger.get na coleta completa. Menor que page_size
        #: de propósito: trigger.get com todos os selects usados aqui é uma
        #: consulta pesada por host — um lote grande demais pode devolver HTTP
        #: 500 (timeout/memória) no servidor Zabbix.
        self.trigger_batch_size = max(1, trigger_batch_size)
        #: Tentativas extras por chamada quando o erro é transitório (HTTP 5xx).
        self.max_retries = max(0, int(max_retries))
        #: Backoff progressivo: espera `retry_backoff * 2**tentativa` segundos.
        self.retry_backoff = float(retry_backoff)
        self.retry_backoff_max = float(retry_backoff_max)
        #: Piso da redução adaptativa de lote — abaixo disto não adianta dividir.
        self.min_page_size = max(1, int(min_page_size))
        self._sleep = sleep
        self._transport = transport or RequestsTransport(self.endpoint, timeout=timeout, verify=verify_tls)

        #: Contadores de resiliência, gravados nos metadados do snapshot.
        self.retries = 0
        self.transient_errors: list[dict[str, Any]] = []
        self.batch_reductions: list[dict[str, Any]] = []
        self.failed_objects: list[dict[str, Any]] = []
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
            max_retries=settings.max_retries,
            retry_backoff=settings.retry_backoff,
            min_page_size=settings.min_page_size,
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

        result = self._send_with_retry(payload, headers, method)

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
            result = self._send_with_retry(payload, headers, method)

        if isinstance(result, ZabbixError):
            raise result
        return result

    def _send_with_retry(self, payload: dict[str, Any], headers: dict[str, str], method: str) -> Any:
        """`_send` com retry e backoff progressivo para erros transitórios.

        Só erros transitórios são repetidos. Um erro de permissão, de parâmetro
        ou de dados é definitivo: repetir a mesma chamada apenas atrasaria o
        diagnóstico. Quando as tentativas acabam, o erro é propagado como
        `ZabbixTransientError` — quem chama pode então reduzir o lote.
        """
        tentativa = 0
        while True:
            try:
                resultado = self._send(payload, headers, method)
            except ZabbixTransientError as exc:
                erro: ZabbixTransientError | None = exc
            else:
                erro = resultado if isinstance(resultado, ZabbixTransientError) else None
                if erro is None:
                    return resultado

            self.transient_errors.append(
                {
                    "method": method,
                    "attempt": tentativa + 1,
                    "status": getattr(erro, "status", None),
                    "message": str(erro)[:300],
                }
            )
            if tentativa >= self.max_retries:
                raise erro
            espera = min(self.retry_backoff * (2**tentativa), self.retry_backoff_max)
            self.retries += 1
            tentativa += 1
            logger.warning(
                "%s falhou (%s); tentativa %d/%d em %.1fs",
                method, erro, tentativa, self.max_retries, espera,
            )
            self._sleep(espera)

    def _send(self, payload: dict[str, Any], headers: dict[str, str], method: str) -> Any:
        try:
            body = self._transport(payload, headers)
        except ZabbixTransientError:
            # A chamada que morreu no transporte também entra no log de
            # auditoria do snapshot — senão o retry ficaria invisível.
            self.call_log.append({"method": method, "params": self._sanitize_params(payload.get("params")), "ok": False})
            raise

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
            if any(hint in lowered for hint in _TRANSIENT_HINTS):
                # HTTP 200 com erro de timeout/memória no corpo: o Zabbix nem
                # sempre devolve 500 quando a consulta é grande demais.
                return ZabbixTransientError(f"{method} -> {message}")
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

    def get_by_ids(
        self,
        method: str,
        id_field: str,
        ids: Iterable[str],
        params: dict[str, Any],
        *,
        page_size: int | None = None,
        on_page: Callable[[dict[str, Any]], None] = lambda _e: None,
        label: str = "",
    ) -> list[dict[str, Any]]:
        """Executa `method` em lotes para uma lista de IDs, concatenando resultados.

        Esta é a paginação real desta integração. A API do Zabbix **não tem
        `offset`** — `limit` sozinho não permite avançar por um conjunto grande.
        O que funciona é paginar por conjunto de IDs: descobrir os IDs do escopo
        com uma consulta barata (`output: ["...id"]`, sem `select*`) e depois
        hidratar em lotes. Como efeito colateral bom, o total passa a ser
        conhecido de verdade — o progresso não precisa ser estimado.
        """
        unique = sorted({str(i) for i in ids if str(i) not in ("", "0")}, key=_id_sort_key)
        return self.fetch_in_chunks(
            method, id_field, unique, params, page_size=page_size, on_page=on_page, label=label
        )

    def fetch_in_chunks(
        self,
        method: str,
        id_field: str,
        ids: Sequence[str],
        params: dict[str, Any],
        *,
        page_size: int | None = None,
        on_page: Callable[[dict[str, Any]], None] = lambda _e: None,
        label: str = "",
    ) -> list[dict[str, Any]]:
        """Hidrata `ids` em páginas, reduzindo o lote quando o servidor recusa.

        A redução adaptativa é o que resolve o HTTP 500 observado no ambiente
        real: uma página grande demais é dividida ao meio e cada metade é
        tentada de novo (500 -> 250 -> 125 -> ...), até o piso `min_page_size`.
        Abaixo do piso não se divide mais: uma falha que persiste com 25 IDs é
        sistemática, e insistir viraria 25 requisições que também falhariam. Os
        objetos dessa página são registrados como não coletados — e isso aparece
        no relatório, nunca é mascarado.
        """
        tamanho = max(1, int(page_size or self.page_size))
        # O piso existe para não transformar uma falha sistemática em centenas
        # de requisições de um objeto cada, todas falhando.
        piso = max(1, min(self.min_page_size, tamanho))
        coletados: list[dict[str, Any]] = []
        total = len(ids)

        for linhas, lote, pagina, restantes in self._paginate(
            method, id_field, list(ids), params, chunk_size=tamanho, floor=piso, on_page=on_page, label=label
        ):
            coletados.extend(linhas)
            on_page(
                {
                    "event": "page",
                    "label": label or method,
                    "method": method,
                    "page": pagina,
                    "page_size": len(lote),
                    "rows": len(linhas),
                    "collected": len(coletados),
                    "total": total,
                    "remaining_pages": restantes,
                }
            )
        return coletados

    def _paginate(
        self,
        method: str,
        id_field: str,
        ids: list[str],
        params: dict[str, Any],
        *,
        chunk_size: int,
        floor: int,
        on_page: Callable[[dict[str, Any]], None],
        label: str,
    ) -> Iterator[tuple[list[dict[str, Any]], list[str], int, int]]:
        """Percorre `ids` em páginas, dividindo o lote quando o servidor recusa.

        Devolve (linhas, lote, número da página, páginas restantes) por página
        bem-sucedida. Páginas que falham definitivamente são registradas em
        `failed_objects` e puladas — a coleta continua parcial, nunca silenciosa.
        """
        pendentes: list[list[str]] = list(chunked(ids, chunk_size))
        pagina = 0

        while pendentes:
            lote = pendentes.pop(0)
            pagina += 1
            try:
                linhas = self.call(method, {**params, id_field: lote}) or []
            except ZabbixTransientError as exc:
                if len(lote) > floor:
                    meio = len(lote) // 2
                    # Reinsere as metades no início: a página menor é tentada já.
                    pendentes[0:0] = [lote[:meio], lote[meio:]]
                    self.batch_reductions.append(
                        {"method": method, "from": len(lote), "to": meio, "reason": str(exc)[:200]}
                    )
                    on_page(
                        {
                            "event": "batch_reduced",
                            "label": label or method,
                            "method": method,
                            "from_size": len(lote),
                            "to_size": meio,
                            "error": str(exc)[:200],
                        }
                    )
                    continue
                self.failed_objects.extend(
                    {"method": method, "id": objeto, "error": str(exc)[:200]} for objeto in lote
                )
                on_page({"event": "page_failed", "label": label or method, "method": method, "ids": lote,
                         "error": str(exc)[:200]})
                continue

            yield linhas, lote, pagina, len(pendentes)

    def discover_ids(
        self,
        method: str,
        id_field: str,
        filter_field: str,
        filter_values: Sequence[str],
        params: dict[str, Any],
        *,
        chunk_size: int,
        on_page: Callable[[dict[str, Any]], None] = lambda _e: None,
        label: str = "",
    ) -> list[str]:
        """Descobre IDs consultando por lotes de um campo de filtro (ex.: `hostids`).

        Mesma redução adaptativa da hidratação, mas com **piso 1**: a resposta da
        descoberta é minúscula (só IDs), então dividir até um host por chamada
        continua barato — e é muito melhor do que perder todos os triggers de um
        lote de hosts porque um deles é pesado.
        """
        vistos: dict[str, None] = {}
        for linhas, lote, pagina, restantes in self._paginate(
            method, filter_field, list(filter_values), {**params, "output": [id_field]},
            chunk_size=chunk_size, floor=1, on_page=on_page, label=label,
        ):
            for linha in linhas:
                valor = str(linha.get(id_field) or "")
                if valor and valor != "0":
                    vistos.setdefault(valor, None)
            on_page(
                {
                    "event": "phase",
                    "name": label or f"descoberta ({method})",
                    "detail": f"lote {pagina} ({len(lote)} de {filter_field}), "
                              f"{len(vistos)} encontrados, {restantes} lote(s) restante(s)",
                }
            )
        return sorted(vistos, key=_id_sort_key)

    def list_ids(self, method: str, id_field: str, params: dict[str, Any]) -> list[str]:
        """Consulta barata que devolve só os IDs do escopo (`output: [id]`).

        É o primeiro passo da paginação: sem `select*` e sem campos de texto, a
        resposta é pequena mesmo com dezenas de milhares de objetos, e passa a
        ser o total confiável usado no progresso.
        """
        rows = self.call(method, {**params, "output": [id_field]}) or []
        vistos: list[str] = []
        conhecidos: set[str] = set()
        for row in rows:
            valor = str(row.get(id_field) or "")
            if valor and valor not in ("0",) and valor not in conhecidos:
                conhecidos.add(valor)
                vistos.append(valor)
        return sorted(vistos, key=_id_sort_key)


def _id_sort_key(value: str) -> tuple[int, Any]:
    """Ordena IDs numericamente quando possível — páginas determinísticas.

    A ordem estável importa para o resume: a mesma lista de IDs precisa render
    as mesmas páginas em execuções diferentes.
    """
    return (0, int(value)) if value.isdigit() else (1, value)
