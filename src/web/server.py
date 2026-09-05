"""Servidor HTTP local da interface.

## Por que `http.server` e não Flask/FastAPI

O projeto inteiro tem **uma** dependência externa (`requests`). Isto aqui é uma
ferramenta local, de um operador por vez, servindo dados de um arquivo em
disco: não há multi-tenancy, nem autenticação, nem carga concorrente. A
biblioteca padrão resolve, e continuar com `pip install -r requirements.txt`
trazendo uma linha só vale mais do que qualquer conveniência de framework.

## Segurança

* **Escuta só em localhost** por padrão. Servir na rede exige `--host` explícito,
  e o servidor avisa o que isso significa: qualquer pessoa na rede veria a
  configuração de monitoramento inteira, sem senha.
* **Nenhuma credencial do Zabbix chega aqui.** Este processo lê arquivos; não
  importa `zabbix_client`, não lê `ZABBIX_API_TOKEN`, não abre conexão com o
  Zabbix. A garantia é estrutural.
* **Escrita só em `docs/alerts/`**, e só por `POST /api/procedures/<id>`.
* Arquivos estáticos são servidos de um diretório fixo, com o caminho
  normalizado antes de qualquer acesso — `..` não escapa dali.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlparse

from ..scope import ScopeError, load_scopes
from . import api
from .readmodel import ReadModelCache

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".json": "application/json; charset=utf-8",
}

#: Corpo máximo aceito num POST de procedimento. Um procedimento é texto que
#: uma pessoa escreveu; 1 MB é folgado e evita que um cliente errado ocupe a
#: memória do processo.
MAX_BODY = 1024 * 1024


class WebApp:
    """Roteia requisições para as funções de `api`. Sem estado de sessão."""

    def __init__(
        self,
        output_dir: str = "output",
        docs_dir: str = "docs/alerts",
        snapshot: str | None = None,
        scopes_file: str | None = None,
    ):
        self.cache = ReadModelCache(output_dir, docs_dir, snapshot, scopes=load_scopes(scopes_file))
        self.docs_dir = docs_dir

    # ------------------------------------------------------------------- rotas
    def handle(self, method: str, path: str, params: dict[str, list[str]], body: bytes) -> tuple[int, Any]:
        """Devolve `(status, payload)`. Levanta nada: erros viram payload."""
        try:
            if method == "GET":
                return 200, self._get(path, params)
            if method == "POST":
                return self._post(path, body, params)
            return 405, {"error": f"Método {method} não suportado."}
        except api.ApiError as exc:
            return exc.status, {"error": str(exc)}
        except ScopeError as exc:
            return 400, {"error": str(exc)}
        except FileNotFoundError as exc:
            return 503, {
                "error": str(exc),
                "hint": "Rode `python main.py collect` para gerar um snapshot.",
            }
        except Exception as exc:  # pragma: no cover - rede de segurança
            logger.exception("Erro inesperado em %s %s", method, path)
            return 500, {"error": f"Erro interno: {exc}"}

    def _get(self, path: str, params: dict[str, list[str]]) -> Any:
        # O escopo vem da query string, como qualquer filtro — assim uma tela
        # colada num chamado abre igual do outro lado.
        escopo = (params.get("scope") or [None])[0]
        modelo = self.cache.get(escopo)
        partes = [p for p in path.strip("/").split("/") if p]

        # /api/<recurso>[/<id>]
        if len(partes) < 2 or partes[0] != "api":
            raise api.ApiError(f"Rota desconhecida: {path}", 404)
        recurso = partes[1]
        identificador = unquote(partes[2]) if len(partes) > 2 else ""

        if recurso == "dashboard":
            return api.dashboard(modelo, params)
        if recurso == "alerts":
            return api.alert_detail(modelo, identificador) if identificador else api.alerts(modelo, params)
        if recurso == "families":
            return (
                api.family_detail(modelo, identificador, params) if identificador
                else api.families(modelo, params)
            )
        if recurso == "hosts":
            return api.host_detail(modelo, identificador, params) if identificador else api.hosts(modelo, params)
        if recurso == "host-groups":
            return (
                api.host_group_detail(modelo, identificador, params) if identificador
                else api.host_groups(modelo, params)
            )
        if recurso == "procedures":
            return api.procedures(modelo, params)
        if recurso == "rules":
            if not identificador:
                return api.rules(modelo, params)
            sub = partes[3] if len(partes) > 3 else ""
            if sub == "instances":
                return api.rule_instances(modelo, identificador, params)
            if sub == "alerts":
                return api.rule_alerts(modelo, identificador, params)
            if sub == "families":
                return api.rule_families(modelo, identificador, params)
            if sub == "suggestions":
                return api.rule_suggestions(modelo, identificador, params)
            if sub:
                raise api.ApiError(f"Sub-recurso desconhecido de regra: {sub}", 404)
            return api.rule_detail(modelo, identificador, params)
        if recurso == "groups":
            if not identificador:
                return api.groups(modelo, params)
            if len(partes) > 3 and partes[3] == "rules":
                return api.rules(modelo, {**params, "group": [identificador]})
            return api.group_detail(modelo, identificador, params)
        if recurso == "collisions":
            return api.collisions(modelo, params)
        if recurso == "status":
            return api.status(modelo, self.cache, params)
        if recurso == "search":
            return api.search(modelo, params)
        if recurso == "scopes":
            return {"scopes": self.cache.scopes.listar(), "default": self.cache.scopes.default_id}
        raise api.ApiError(f"Recurso desconhecido: {recurso}", 404)

    def _post(self, path: str, body: bytes, params: dict[str, list[str]]) -> tuple[int, Any]:
        partes = [p for p in path.strip("/").split("/") if p]

        def corpo_json() -> dict[str, Any]:
            try:
                carga = json.loads(body.decode("utf-8") or "{}")
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise api.ApiError(f"JSON inválido: {exc}", 400) from exc
            if not isinstance(carga, dict):
                raise api.ApiError("Corpo precisa ser um objeto JSON.", 400)
            return carga

        # AS ÚNICAS ESCRITAS DO SISTEMA — todas locais, em docs/.
        # Procedimento de família: /api/procedures/<família>
        if len(partes) == 3 and partes[:2] == ["api", "procedures"]:
            # A família é procurada no ambiente inteiro: escrever um
            # procedimento é permitido mesmo para uma família que o escopo
            # atual não mostra. O escopo filtra a visão, não o conhecimento.
            modelo = self.cache.get("all")
            resultado = api.save_procedure(modelo, unquote(partes[2]), corpo_json(), self.docs_dir)
            self.cache.invalidate()
            return 200, resultado

        # Procedimento de regra e decisão sobre o candidato.
        if len(partes) == 4 and partes[:2] == ["api", "rules"]:
            escopo = (params.get("scope") or [None])[0]
            modelo = self.cache.get(escopo)
            identificador = unquote(partes[2])
            if partes[3] == "procedure":
                resultado = api.save_procedure(modelo, identificador, corpo_json(),
                                               self.docs_dir, kind="rule")
                self.cache.invalidate()
                return 200, resultado
            if partes[3] == "decision":
                resultado = api.decide_rule(modelo, identificador, corpo_json())
                self.cache.invalidate()
                return 200, resultado

        raise api.ApiError(f"Rota desconhecida para POST: {path}", 404)


def _arquivo_estatico(path: str) -> Path | None:
    """Resolve um caminho estático sem deixar escapar de STATIC_DIR."""
    relativo = path.lstrip("/") or "index.html"
    alvo = (STATIC_DIR / relativo).resolve()
    try:
        alvo.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return None  # tentativa de subir de diretório
    return alvo if alvo.is_file() else None


def make_handler(app: WebApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "ZabbixWiki"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, formato: str, *args: Any) -> None:
            logger.debug("%s - %s", self.address_string(), formato % args)

        # ---------------------------------------------------------- utilitários
        def _responder(self, status: int, corpo: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(corpo)))
            # A interface não carrega nada de fora; a CSP torna isso explícito e
            # impede que um dado do Zabbix vire origem de requisição externa.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(corpo)

        def _json(self, status: int, payload: Any) -> None:
            corpo = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self._responder(status, corpo, "application/json; charset=utf-8")

        # --------------------------------------------------------------- verbos
        def do_GET(self) -> None:  # noqa: N802 - assinatura da stdlib
            url = urlparse(self.path)
            if url.path.startswith("/api/"):
                status, payload = app.handle("GET", url.path, parse_qs(url.query), b"")
                self._json(status, payload)
                return

            arquivo = _arquivo_estatico(url.path)
            if arquivo is None:
                # Rotas da interface (/alerts/123) são resolvidas no navegador:
                # qualquer caminho não-API devolve o index e o app roteia.
                arquivo = STATIC_DIR / "index.html"
                if not arquivo.is_file():
                    self._json(404, {"error": "Interface não encontrada."})
                    return
            self._responder(200, arquivo.read_bytes(), MIME.get(arquivo.suffix, "application/octet-stream"))

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_POST(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            try:
                tamanho = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                tamanho = 0
            if tamanho > MAX_BODY:
                self._json(413, {"error": f"Corpo maior que {MAX_BODY} bytes."})
                return
            corpo = self.rfile.read(tamanho) if tamanho else b""
            status, payload = app.handle("POST", url.path, parse_qs(url.query), corpo)
            self._json(status, payload)

        def do_PUT(self) -> None:  # noqa: N802
            self._json(405, {"error": "Método não suportado."})

        def do_DELETE(self) -> None:  # noqa: N802
            self._json(405, {"error": "Método não suportado."})

    return Handler


def serve(
    output_dir: str = "output",
    docs_dir: str = "docs/alerts",
    snapshot: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    on_ready: Callable[[str], None] = lambda _url: None,
    scopes_file: str | None = None,
) -> ThreadingHTTPServer:
    """Sobe o servidor e devolve a instância (para testes e para o `serve` da CLI)."""
    app = WebApp(output_dir=output_dir, docs_dir=docs_dir, snapshot=snapshot, scopes_file=scopes_file)
    servidor = ThreadingHTTPServer((host, port), make_handler(app))
    servidor.daemon_threads = True
    porta = servidor.server_address[1]
    on_ready(f"http://{host if host != '0.0.0.0' else socket.gethostname()}:{porta}/")
    return servidor


def serve_forever(
    output_dir: str = "output",
    docs_dir: str = "docs/alerts",
    snapshot: str | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    on_ready: Callable[[str], None] = lambda _url: None,
    scopes_file: str | None = None,
) -> None:
    servidor = serve(output_dir, docs_dir, snapshot, host, port, on_ready, scopes_file)
    hilo = threading.Thread(target=servidor.serve_forever, daemon=True)
    hilo.start()
    try:
        hilo.join()
    except KeyboardInterrupt:
        servidor.shutdown()
