"""Modelo de leitura: snapshot + fichas -> índices para a interface.

## O que este módulo é

Uma projeção de leitura sobre dados que já existem. Ele NÃO define um segundo
modelo de domínio:

* os alertas vêm de `normalized/alerts.json`, com o formato que a Fase 1 já
  produzia;
* a família de um alerta é `core.models.build_family_key(alert)` — a **mesma**
  função que o `reconcile` usa para nomear a ficha. É isso que faz o link
  família → procedimento ser exato em vez de aproximado;
* o procedimento é o `AlertDoc` que o `AlertRepository` lê de `docs/alerts/`,
  com o `procedure_status` que o próprio modelo deriva.

Se a regra de família mudar em `core/models.py`, a interface acompanha sozinha.

## Escala

O ambiente real tem ~19.000 alertas, o que dá um `alerts.json` de ~50 MB. Ele é
carregado uma vez e mantido em memória; as consultas trabalham sobre índices
construídos nesse momento. Duas decisões de custo:

* **haystack por alerta**: uma string minúscula e sem acentos, montada uma vez,
  com descrição + host + grupos + tags + comentário + chaves de item. A busca
  é substring sobre ela. 19k comparações levam milissegundos e evitam manter um
  índice invertido que precisaria ser invalidado.
* **recarga por mtime**: o snapshot é imutável, mas o operador pode rodar uma
  coleta nova com a interface aberta. Em vez de vigiar arquivos, comparamos o
  caminho e o mtime a cada requisição — barato e sem thread de fundo.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from ..core.models import build_family_key
from ..core.repository import AlertRepository
from ..keys import normalize_text, short_hash, slugify
from ..scope import ALL_SCOPE_ID, EVERYTHING, OperationalScope, ScopeConfig

#: Ordem de severidade do Zabbix, do mais grave para o menos.
SEVERIDADES = ["Disaster", "High", "Average", "Warning", "Information", "Not classified"]
_ORDEM_SEVERIDADE = {nome: indice for indice, nome in enumerate(SEVERIDADES)}

#: Estados de procedimento expostos na interface (derivados de `doc_status`).
PROCEDURE_STATUSES = ["missing", "draft", "documented", "needs_review", "not_applicable"]

#: Rótulo legível de cada estado — a interface nunca mostra o nome interno.
PROCEDURE_LABELS = {
    "missing": "Ausente",
    "draft": "Rascunho",
    "documented": "Validado",
    "needs_review": "Precisa de revisão",
    "not_applicable": "Não aplicável",
}


def _snapshot_dirs(output_dir: str | Path) -> list[Path]:
    raiz = Path(output_dir) / "snapshots"
    if not raiz.is_dir():
        return []
    return sorted(
        (d for d in raiz.iterdir()
         if d.is_dir() and not d.is_symlink() and (d / "normalized" / "alerts.json").is_file()),
        key=lambda d: d.name,
    )


def resolve_snapshot(output_dir: str | Path, escolhido: str | None = None) -> Path:
    """Decide qual snapshot a interface serve.

    Sem escolha explícita, vence o mais recente **que não seja parcial**: um
    snapshot parcial é material de auditoria, não base de consulta, e servi-lo
    por engano mostraria um ambiente menor do que ele é.
    """
    if escolhido:
        caminho = Path(escolhido)
        if caminho.is_dir():
            return caminho
        raise FileNotFoundError(f"Snapshot não encontrado: {escolhido}")

    candidatos = _snapshot_dirs(output_dir)
    if not candidatos:
        raise FileNotFoundError(
            f"Nenhum snapshot em {output_dir}/snapshots. Rode `python main.py collect` antes."
        )
    completos = [d for d in candidatos if "parcial" not in d.name]
    return (completos or candidatos)[-1]


@dataclass
class Familia:
    """Uma regra operacional — o nível em que o procedimento costuma ser único."""

    id: str
    key: str
    label: str
    origin: str
    discovery_rule: str = ""
    alert_ids: list[str] = field(default_factory=list)
    hosts: dict[str, str] = field(default_factory=dict)
    host_groups: set[str] = field(default_factory=set)
    severities: dict[str, int] = field(default_factory=dict)
    signatures: set[str] = field(default_factory=set)
    discovered: bool = False

    def resumo(self, procedimento: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "label": self.label,
            "origin": self.origin,
            "discovered": self.discovered,
            "alerts": len(self.alert_ids),
            "hosts": len(self.hosts),
            "host_groups": sorted(self.host_groups),
            "severities": ordenar_severidades(self.severities),
            "distinct_expressions": len(self.signatures),
            "procedure": procedimento,
        }


def ordenar_severidades(contagem: dict[str, int]) -> dict[str, int]:
    return dict(sorted(contagem.items(), key=lambda kv: _ORDEM_SEVERIDADE.get(kv[0], 99)))


def _haystack(alerta: dict[str, Any], familia_label: str) -> str:
    """Texto pesquisável de um alerta, montado uma vez no carregamento."""
    zbx = alerta.get("zabbix") or {}
    host = zbx.get("host") or {}
    partes = [
        zbx.get("description_raw", ""),
        zbx.get("event_name", ""),
        zbx.get("comments", ""),
        zbx.get("opdata", ""),
        host.get("name", ""),
        host.get("host", ""),
        alerta.get("alert_key", ""),
        familia_label,
        zbx.get("prototype_description") or "",
        (zbx.get("discovery_rule") or {}).get("name", "") if zbx.get("discovery_rule") else "",
        " ".join(zbx.get("host_groups") or []),
        " ".join(f"{t.get('tag')} {t.get('value')}" for t in zbx.get("tags") or []),
        " ".join(i.get("key_", "") for i in zbx.get("items") or []),
        " ".join(i.get("name", "") for i in zbx.get("items") or []),
    ]
    return normalize_text(" ".join(p for p in partes if p))


def _nomes_do_host(alerta: dict[str, Any]) -> tuple[str, str]:
    host = (alerta.get("zabbix") or {}).get("host") or {}
    return str(host.get("name") or ""), str(host.get("host") or "")


def _particionar(
    alertas: list[dict[str, Any]], scope: OperationalScope
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Separa os alertas em (dentro do escopo, fora do escopo).

    Os de fora **não são descartados**: continuam disponíveis para o dashboard
    dizer quanto ficou de fora e para a busca avisar que existem resultados
    além do escopo. Esconder sem contar seria enganoso.
    """
    if scope.is_everything:
        return list(alertas), []
    dentro: list[dict[str, Any]] = []
    fora: list[dict[str, Any]] = []
    for alerta in alertas:
        (dentro if scope.includes_host(*_nomes_do_host(alerta)) else fora).append(alerta)
    return dentro, fora


def _contar_ambiente(alertas: list[dict[str, Any]]) -> dict[str, int]:
    """Números do AMBIENTE COLETADO, independentes do escopo.

    O dashboard mostra as duas visões lado a lado; sem isto o operador veria o
    número do NOC sem saber que existe um ambiente maior atrás dele.
    """
    hosts: set[str] = set()
    grupos: set[str] = set()
    familias: set[str] = set()
    for alerta in alertas:
        zbx = alerta.get("zabbix") or {}
        hostid = str((zbx.get("host") or {}).get("hostid") or "")
        if hostid:
            hosts.add(hostid)
        grupos.update(zbx.get("host_groups") or [])
        familias.add(build_family_key(alerta))
    return {
        "alerts": len(alertas),
        "hosts": len(hosts),
        "host_groups": len(grupos),
        "families": len(familias),
    }


class ReadModel:
    """Snapshot carregado e indexado, pronto para as consultas da interface."""

    def __init__(
        self,
        snapshot_dir: Path,
        docs_dir: str | Path = "docs/alerts",
        scope: OperationalScope = EVERYTHING,
    ):
        self.snapshot_dir = Path(snapshot_dir)
        self.docs_dir = Path(docs_dir)
        self.scope = scope
        self.loaded_at = ""

        payload = json.loads((self.snapshot_dir / "normalized" / "alerts.json").read_text(encoding="utf-8"))
        self.meta: dict[str, Any] = payload.get("meta") or {}
        coletados: list[dict[str, Any]] = payload.get("alerts") or []

        # O escopo é aplicado AQUI e em nenhum outro lugar. Hosts, host groups,
        # famílias, severidades e procedimentos são todos derivados desta lista
        # em `_indexar()`, então filtrar a entrada propaga para todos os
        # indicadores sem tocar em um único cálculo de métrica.
        self.alerts, self.out_of_scope = _particionar(coletados, scope)

        self.collisions: list[dict[str, Any]] = self._ler_colisoes()
        self.report: dict[str, Any] = self._ler_report()

        self.by_trigger: dict[str, dict[str, Any]] = {}
        self.families: dict[str, Familia] = {}
        self.family_of: dict[str, str] = {}
        self.hosts: dict[str, dict[str, Any]] = {}
        self.host_groups: dict[str, dict[str, Any]] = {}
        self.haystacks: dict[str, str] = {}
        #: Textos pesquisáveis do que ficou FORA do escopo, montados uma vez.
        #: Sem isto a busca global normalizaria 16 mil textos a cada tecla só
        #: para dizer quantos resultados existem além do escopo — o aviso
        #: custaria dez vezes mais que a busca inteira.
        self.haystacks_out: list[str] = []
        self.collision_keys: set[str] = set()

        self._indexar()
        self._carregar_procedimentos()
        self.environment = _contar_ambiente(coletados)

    # ------------------------------------------------------------------ carga
    def _ler_json(self, *partes: str) -> dict[str, Any]:
        caminho = self.snapshot_dir.joinpath(*partes)
        if not caminho.is_file():
            return {}
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _ler_colisoes(self) -> list[dict[str, Any]]:
        """Colisões do snapshot, recortadas pelo escopo.

        Uma colisão entra na visão quando **pelo menos uma** ocorrência está no
        escopo. As demais ocorrências continuam visíveis, marcadas com
        `in_scope: false`: esconder o outro lado tornaria a colisão
        incompreensível — não dá para analisar com o que a chave colidiu sem
        ver o que colidiu.
        """
        todas = (self._ler_json("normalized", "collisions.json") or {}).get("collisions") or []
        self.collisions_total = len(todas)
        if self.scope.is_everything:
            return todas

        dentro: list[dict[str, Any]] = []
        for colisao in todas:
            ocorrencias = []
            alguma_no_escopo = False
            for ocorrencia in colisao.get("occurrences") or []:
                no_escopo = self.scope.includes_host(
                    str(ocorrencia.get("host") or ""), str(ocorrencia.get("host_technical") or "")
                )
                alguma_no_escopo = alguma_no_escopo or no_escopo
                ocorrencias.append({**ocorrencia, "in_scope": no_escopo})
            if alguma_no_escopo:
                dentro.append({**colisao, "occurrences": ocorrencias})
        return dentro

    def _ler_report(self) -> dict[str, Any]:
        return self._ler_json("report.json")

    def _indexar(self) -> None:
        self.collision_keys = {c.get("alert_key", "") for c in self.collisions}

        for alerta in self.alerts:
            zbx = alerta.get("zabbix") or {}
            triggerid = str(zbx.get("triggerid") or "")
            if not triggerid:
                continue
            self.by_trigger[triggerid] = alerta

            familia = self._familia_de(alerta)
            familia.alert_ids.append(triggerid)
            self.family_of[triggerid] = familia.id

            host = zbx.get("host") or {}
            hostid = str(host.get("hostid") or "")
            nome_host = host.get("name") or host.get("host") or "(sem host)"
            if hostid:
                familia.hosts[hostid] = nome_host
                self._host(hostid, host, alerta, familia)

            grupos = zbx.get("host_groups") or []
            familia.host_groups.update(grupos)
            for grupo in grupos:
                self._grupo(grupo, hostid, triggerid, familia)

            severidade = (zbx.get("priority") or {}).get("name", "Not classified")
            familia.severities[severidade] = familia.severities.get(severidade, 0) + 1
            if zbx.get("expression_signature"):
                familia.signatures.add(zbx["expression_signature"])

            self.haystacks[triggerid] = _haystack(alerta, familia.label)

        for alerta in self.out_of_scope:
            self.haystacks_out.append(_haystack(alerta, ""))

    def _familia_de(self, alerta: dict[str, Any]) -> Familia:
        # A MESMA chave que o reconcile usa para nomear a ficha.
        chave = build_family_key(alerta)
        identificador = short_hash(chave, 12)
        familia = self.families.get(identificador)
        if familia is not None:
            return familia

        zbx = alerta.get("zabbix") or {}
        descoberto = bool(zbx.get("discovered") and zbx.get("prototype_description"))
        regra = (zbx.get("discovery_rule") or {}).get("name", "") if zbx.get("discovery_rule") else ""
        familia = Familia(
            id=identificador,
            key=chave,
            label=(zbx.get("prototype_description") if descoberto else zbx.get("description_raw")) or "(sem nome)",
            origin=(f"LLD: {regra}" if regra else "LLD") if descoberto else "trigger direto",
            discovery_rule=regra,
            discovered=descoberto,
        )
        self.families[identificador] = familia
        return familia

    def _host(self, hostid: str, host: dict[str, Any], alerta: dict[str, Any], familia: Familia) -> None:
        registro = self.hosts.get(hostid)
        if registro is None:
            registro = {
                "id": hostid,
                "name": host.get("name") or host.get("host") or "(sem nome)",
                "technical_name": host.get("host") or "",
                "status": (host.get("status") or {}).get("name", ""),
                "inventory": host.get("inventory") or {},
                "host_groups": [],
                "alert_ids": [],
                "family_ids": set(),
                "severities": {},
                "discovered": 0,
            }
            self.hosts[hostid] = registro

        zbx = alerta["zabbix"]
        registro["alert_ids"].append(str(zbx["triggerid"]))
        registro["family_ids"].add(familia.id)
        severidade = (zbx.get("priority") or {}).get("name", "Not classified")
        registro["severities"][severidade] = registro["severities"].get(severidade, 0) + 1
        if zbx.get("discovered"):
            registro["discovered"] += 1
        for grupo in zbx.get("host_groups") or []:
            if grupo not in registro["host_groups"]:
                registro["host_groups"].append(grupo)

    def _grupo(self, nome: str, hostid: str, triggerid: str, familia: Familia) -> None:
        identificador = slugify(nome, fallback=short_hash(nome))
        registro = self.host_groups.get(identificador)
        if registro is None:
            registro = {
                "id": identificador,
                "name": nome,
                "host_ids": set(),
                "alert_ids": [],
                "family_ids": set(),
                "severities": {},
            }
            self.host_groups[identificador] = registro
        if hostid:
            registro["host_ids"].add(hostid)
        registro["alert_ids"].append(triggerid)
        registro["family_ids"].add(familia.id)
        alerta = self.by_trigger[triggerid]
        severidade = (alerta["zabbix"].get("priority") or {}).get("name", "Not classified")
        registro["severities"][severidade] = registro["severities"].get(severidade, 0) + 1

    def _carregar_procedimentos(self) -> None:
        """Lê as fichas de `docs/alerts/` e as liga às famílias pela chave."""
        self.procedures: dict[str, dict[str, Any]] = {}
        repositorio = AlertRepository(self.docs_dir)
        por_chave = {doc.alert_key: doc for doc in repositorio.all()}

        for familia in self.families.values():
            doc = por_chave.get(familia.key)
            self.procedures[familia.id] = _procedimento(doc, familia)

    # ------------------------------------------------------------- acessadores
    def procedure_of_family(self, family_id: str) -> dict[str, Any]:
        return self.procedures.get(family_id) or _procedimento(None, None)

    def procedure_of_alert(self, triggerid: str) -> dict[str, Any]:
        return self.procedure_of_family(self.family_of.get(triggerid, ""))

    def family_of_alert(self, triggerid: str) -> Familia | None:
        return self.families.get(self.family_of.get(triggerid, ""))

    def count_out_of_scope(self, termo: str) -> int:
        """Quantos alertas fora do escopo casariam com a busca."""
        agulha = normalize_text(termo)
        if not agulha or not self.haystacks_out:
            return 0
        return sum(1 for feno in self.haystacks_out if agulha in feno)

    def search_ids(self, termo: str) -> list[str] | None:
        """IDs cujo haystack contém o termo. `None` quando não há busca."""
        agulha = normalize_text(termo)
        if not agulha:
            return None
        return [tid for tid, feno in self.haystacks.items() if agulha in feno]


def _procedimento(doc: Any, familia: Familia | None) -> dict[str, Any]:
    """Bloco de procedimento exposto pela API.

    As três camadas continuam separadas aqui, com nomes diferentes e origem
    declarada: `operational` é humano, `ai_suggestion` é sugestão, e o que veio
    do Zabbix nem entra neste bloco. Sem ficha, o estado é `missing` — nunca um
    procedimento inventado para preencher a tela.
    """
    if doc is None:
        return {
            "status": "missing",
            "label": PROCEDURE_LABELS["missing"],
            "exists": False,
            "doc_status": "undocumented",
            "operational": None,
            "ai_suggestion": None,
            "reviewed_by": "",
            "reviewed_at": None,
            "last_modified_at": None,
            "revision": 0,
            "family_key": familia.key if familia else "",
        }
    return {
        "status": doc.procedure_status,
        "label": PROCEDURE_LABELS.get(doc.procedure_status, doc.procedure_status),
        "exists": True,
        "doc_status": doc.doc_status,
        "operational": doc.operational,
        "ai_suggestion": doc.ai_suggestion,
        "reviewed_by": (doc.operational or {}).get("reviewed_by", ""),
        "reviewed_at": (doc.operational or {}).get("reviewed_at"),
        "last_modified_at": doc.last_modified_at,
        "revision": doc.revision,
        "family_key": doc.alert_key,
    }


class ReadModelCache:
    """Mantém um `ReadModel` carregado, recarregando quando o snapshot muda.

    O snapshot é imutável, mas o operador pode rodar `collect` com a interface
    aberta, e as fichas de `docs/alerts/` mudam a cada `reconcile` — ou a cada
    edição feita na própria interface. Comparar caminho e mtime a cada
    requisição é barato e dispensa vigiar o filesystem numa thread.
    """

    def __init__(
        self,
        output_dir: str,
        docs_dir: str,
        snapshot: str | None = None,
        scopes: ScopeConfig | None = None,
    ):
        self.output_dir = output_dir
        self.docs_dir = docs_dir
        self.snapshot_escolhido = snapshot
        self.scopes = scopes or ScopeConfig(scopes={ALL_SCOPE_ID: EVERYTHING}, default_id=ALL_SCOPE_ID)
        # Um modelo por escopo. Os dicionários de alerta são compartilhados por
        # referência entre eles — só os índices são reconstruídos —, então o
        # segundo escopo custa dezenas de MB, não outros 290.
        self._modelos: dict[str, ReadModel] = {}
        self._assinatura: tuple[Any, ...] = ()
        self._lock = threading.Lock()

    def _assinatura_atual(self) -> tuple[Any, ...]:
        caminho = resolve_snapshot(self.output_dir, self.snapshot_escolhido)
        alerts = caminho / "normalized" / "alerts.json"
        docs = Path(self.docs_dir)
        # O mtime do diretório de fichas muda quando uma ficha é criada ou
        # removida; a soma dos mtimes cobre a edição de uma ficha existente.
        marca_docs = 0.0
        if docs.is_dir():
            marca_docs = sum(f.stat().st_mtime for f in docs.glob("*.json"))
        return (str(caminho), alerts.stat().st_mtime, marca_docs)

    def get(self, scope_id: str | None = None) -> ReadModel:
        escopo = self.scopes.get(scope_id)
        with self._lock:
            assinatura = self._assinatura_atual()
            if assinatura != self._assinatura:
                self._modelos.clear()  # snapshot ou fichas mudaram
                self._assinatura = assinatura
            modelo = self._modelos.get(escopo.id)
            if modelo is None:
                caminho = resolve_snapshot(self.output_dir, self.snapshot_escolhido)
                modelo = ReadModel(caminho, self.docs_dir, scope=escopo)
                self._modelos[escopo.id] = modelo
            return modelo

    def invalidate(self) -> None:
        with self._lock:
            self._modelos.clear()
            self._assinatura = ()

    def available_snapshots(self) -> list[dict[str, Any]]:
        saida = []
        for caminho in _snapshot_dirs(self.output_dir):
            saida.append({
                "name": caminho.name,
                "path": str(caminho),
                "partial": "parcial" in caminho.name,
                "merged": "consolidado" in caminho.name,
                "size_bytes": sum(f.stat().st_size for f in caminho.rglob("*") if f.is_file()),
            })
        return saida


def paginate(itens: list[Any], page: int, per_page: int) -> tuple[list[Any], dict[str, Any]]:
    """Fatia uma lista e devolve o bloco de paginação usado por toda a API."""
    per_page = max(1, min(int(per_page or 50), 500))
    total = len(itens)
    paginas = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(int(page or 1), paginas))
    inicio = (page - 1) * per_page
    return itens[inicio: inicio + per_page], {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": paginas,
        "has_next": page < paginas,
        "has_prev": page > 1,
    }


def contar_severidades(alertas: Iterable[dict[str, Any]]) -> dict[str, int]:
    contagem: dict[str, int] = {}
    for alerta in alertas:
        nome = ((alerta.get("zabbix") or {}).get("priority") or {}).get("name", "Not classified")
        contagem[nome] = contagem.get(nome, 0) + 1
    return ordenar_severidades(contagem)
