"""Leitura do catálogo do NOC a partir do markdown do wiki.

## Por que markdown, e não um formulário

O catálogo já existe e já é mantido — num wiki, em tabelas. Pedir para a equipe
redigitar 28 procedimentos num formulário seria trocar uma fonte viva por uma
cópia que envelhece. O arquivo `docs/knowledge/catalogo-noc.md` é uma cópia
colável do wiki: quem atualizar o wiki cola a versão nova aqui e roda
`python main.py kb`.

## O que é lido

Três blocos, todos em tabela markdown:

    Matriz de acionamento     fila -> canal, escalonamento, horário
    Tabela de ação rápida     alerta, severidade, host, ação, fila, prazo
    Referência técnica        alerta, descrição, causa provável, referência

As duas tabelas de alerta são unidas pelo nome do alerta — é a chave que o
próprio wiki usa. A fila da tabela de ação é resolvida contra a matriz, e é daí
que sai o canal de escalonamento: o wiki não repete essa informação por alerta,
ele a mantém num lugar só.

## O que NÃO é inferido

Severidade do wiki não vira severidade do Zabbix. São escalas diferentes,
mantidas por pessoas diferentes, e forçar uma correspondência criaria um fato
que ninguém escreveu. A severidade do wiki é transportada como rótulo do wiki.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.models import utc_now
from ..keys import normalize_text, slugify

DEFAULT_CATALOG = Path("docs") / "knowledge" / "catalogo-noc.md"

#: Ícone de severidade do wiki -> rótulo do wiki. Deliberadamente NÃO mapeado
#: para as severidades do Zabbix: são escalas distintas, e casar as duas seria
#: inventar uma equivalência que ninguém validou.
SEVERITY_LABELS = {
    "🔴": "Crítico (wiki)",
    "🟠": "Alto (wiki)",
    "🟡": "Médio (wiki)",
    "🔵": "Baixo (wiki)",
}

#: Reconhece "7 min (5m + 2m)" e "5 min". O total é o prazo até o escalonamento;
#: as parcelas, quando existem, são "espere X, depois acione".
_SLA_TOTAL = re.compile(r"(\d+)\s*min", re.IGNORECASE)
_SLA_PARTES = re.compile(r"\((.+?)\)")
_SLA_PARCELA = re.compile(r"(\d+)\s*m\b", re.IGNORECASE)

#: A ação diz, em português, se o fluxo passa por chamado. É uma leitura de
#: texto — por isso vira SUGESTÃO com a frase de origem anexada, e a ficha
#: entra como rascunho para uma pessoa confirmar.
_PEDE_CHAMADO = re.compile(r"\bchamados?\b", re.IGNORECASE)

#: Ornamentos que não são conteúdo. Os ícones de severidade (🔴🟠🟡🔵) NÃO
#: entram aqui: eles são o valor da coluna "Sev." e precisam sobreviver à
#: limpeza para serem lidos.
_ORNAMENTOS = re.compile(r"[⏱️📘📋☎️🖥️🔐💾🏢🔗⚠️✅❌]")


def _limpar(celula: str) -> str:
    """Remove marcação de tabela, ênfase e código de uma célula."""
    texto = celula.strip()
    texto = texto.replace("`", "").replace("**", "").replace("*", "")
    texto = _ORNAMENTOS.sub("", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _linhas_da_tabela(linhas: list[str], inicio: int) -> tuple[list[list[str]], int]:
    """Lê uma tabela markdown a partir de `inicio`; devolve (linhas, próxima).

    A linha de separadores (`| :--- |`) é descartada, e a leitura para na
    primeira linha que não começa com `|` — que é como o markdown fecha uma
    tabela.
    """
    corpo: list[list[str]] = []
    indice = inicio
    while indice < len(linhas):
        bruta = linhas[indice].strip()
        if not bruta.startswith("|"):
            break
        celulas = [c for c in bruta.strip("|").split("|")]
        if all(set(c.strip()) <= set(": -") and c.strip() for c in celulas):
            indice += 1
            continue  # separador de cabeçalho
        corpo.append([_limpar(c) for c in celulas])
        indice += 1
    return corpo, indice


@dataclass(frozen=True)
class EscalationRow:
    """Uma linha da matriz de acionamento: quem atende o quê, e por onde."""

    team: str
    responsible_for: str = ""
    channel: str = ""
    escalation: str = ""
    schedule: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "team": self.team, "responsible_for": self.responsible_for,
            "channel": self.channel, "escalation": self.escalation, "schedule": self.schedule,
        }


@dataclass(frozen=True)
class Sla:
    """Prazo do wiki, com a frase original preservada."""

    raw: str
    immediate: bool = False
    total_minutes: int | None = None
    parts: tuple[int, ...] = ()

    @property
    def wait_minutes(self) -> int | None:
        """Quanto esperar antes de agir.

        "7 min (5m + 2m)" quer dizer: espere 5, e se não houver resposta acione
        em mais 2. O tempo de espera é a primeira parcela; o total é o prazo até
        o escalonamento. Sem parcelas, o número solto é a própria espera.
        """
        if self.immediate:
            return 0
        if self.parts:
            return self.parts[0]
        return self.total_minutes

    @property
    def escalate_after_minutes(self) -> int | None:
        """Só existe quando o wiki descreve duas etapas."""
        return self.total_minutes if self.parts else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw, "immediate": self.immediate, "total_minutes": self.total_minutes,
            "parts": list(self.parts), "wait_minutes": self.wait_minutes,
            "escalate_after_minutes": self.escalate_after_minutes,
        }


def parse_sla(texto: str) -> Sla:
    limpo = _limpar(texto)
    if not limpo or limpo in ("-", "—"):
        return Sla(raw=limpo)
    if "imediat" in normalize_text(limpo):
        return Sla(raw=limpo, immediate=True, total_minutes=0)
    total = _SLA_TOTAL.search(limpo)
    parentese = _SLA_PARTES.search(limpo)
    parcelas = tuple(int(p) for p in _SLA_PARCELA.findall(parentese.group(1))) if parentese else ()
    return Sla(
        raw=limpo,
        total_minutes=int(total.group(1)) if total else (sum(parcelas) or None),
        parts=parcelas,
    )


def parse_routing(texto: str) -> tuple[str, str]:
    """`Infraestrutura · DeskManager → Teams` -> (time, canal)."""
    limpo = _limpar(texto)
    if "·" in limpo:
        time, _, canal = limpo.partition("·")
        return time.strip(), canal.strip()
    return limpo, ""


@dataclass
class CatalogEntry:
    """Um item do catálogo do NOC, exatamente como o wiki o descreve."""

    id: str
    name: str
    category: str
    severity_icon: str = ""
    severity_label: str = ""
    host: str = ""
    action: str = ""
    routing_raw: str = ""
    team: str = ""
    channel: str = ""
    sla: Sla = field(default_factory=lambda: Sla(raw=""))
    description: str = ""
    probable_cause: str = ""
    reference: str = ""
    escalation: EscalationRow | None = None

    # ------------------------------------------------------------- derivados
    @property
    def requires_ticket(self) -> bool:
        """Leitura da ação, não decisão do sistema — ver `ticket_evidence`."""
        return bool(_PEDE_CHAMADO.search(self.action))

    @property
    def ticket_evidence(self) -> str:
        achado = _PEDE_CHAMADO.search(self.action)
        if not achado:
            return "a ação do wiki não menciona chamado"
        return f"a ação do wiki diz: “{self.action}”"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "severity": {"icon": self.severity_icon, "label": self.severity_label},
            "host": self.host,
            "action": self.action,
            "routing": {"raw": self.routing_raw, "team": self.team, "channel": self.channel},
            "sla": self.sla.to_dict(),
            "description": self.description,
            "probable_cause": self.probable_cause,
            "reference": self.reference,
            "escalation": self.escalation.to_dict() if self.escalation else None,
            "requires_ticket": self.requires_ticket,
            "ticket_evidence": self.ticket_evidence,
        }


@dataclass
class Catalog:
    """O catálogo inteiro: entradas + matriz de acionamento + origem."""

    entries: list[CatalogEntry] = field(default_factory=list)
    escalation: list[EscalationRow] = field(default_factory=list)
    source_path: str = ""
    source_hash: str = ""
    parsed_at: str = field(default_factory=utc_now)

    def get(self, entry_id: str) -> CatalogEntry | None:
        return next((e for e in self.entries if e.id == entry_id), None)

    @property
    def categories(self) -> list[str]:
        vistas: list[str] = []
        for entrada in self.entries:
            if entrada.category not in vistas:
                vistas.append(entrada.category)
        return vistas

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": {"path": self.source_path, "hash": self.source_hash, "parsed_at": self.parsed_at},
            "categories": self.categories,
            "escalation": [linha.to_dict() for linha in self.escalation],
            "entries": [entrada.to_dict() for entrada in self.entries],
        }


class CatalogError(RuntimeError):
    """O catálogo não pôde ser lido."""


def _entry_id(categoria: str, nome: str) -> str:
    """Id estável do item, derivado do texto do wiki.

    Nomes longos ou compostos só de símbolos ainda precisam de um id útil, daí
    o sufixo de hash quando o slug fica vazio ou grande demais.
    """
    base = slugify(nome, fallback="")
    if not base:
        base = f"item-{hashlib.sha256(nome.encode('utf-8')).hexdigest()[:8]}"
    if len(base) > 60:
        base = f"{base[:60].rstrip('-')}-{hashlib.sha256(nome.encode('utf-8')).hexdigest()[:6]}"
    return f"{slugify(categoria, fallback='geral')}--{base}"


def parse_catalog(caminho: str | Path = DEFAULT_CATALOG) -> Catalog:
    """Lê o markdown do wiki e devolve o catálogo estruturado."""
    arquivo = Path(caminho)
    if not arquivo.is_file():
        raise CatalogError(
            f"Catálogo não encontrado em {arquivo}. "
            "Cole a versão atual do wiki do NOC nesse arquivo antes de rodar `kb`."
        )
    texto = arquivo.read_text(encoding="utf-8")
    linhas = texto.splitlines()

    escalacao: list[EscalationRow] = []
    #: nome do alerta (normalizado) -> entrada, para unir as duas tabelas.
    por_nome: dict[str, CatalogEntry] = {}
    ordem: list[CatalogEntry] = []

    categoria = ""
    indice = 0
    while indice < len(linhas):
        linha = linhas[indice].strip()

        if linha.startswith("### "):
            categoria = _limpar(linha[4:])
            indice += 1
            continue

        if linha.startswith("#### "):
            # "Referência técnica — X": a categoria continua sendo a da seção.
            indice += 1
            continue

        if linha.startswith("## "):
            titulo = normalize_text(_limpar(linha[3:]))
            if "matriz" in titulo:
                corpo, indice = _linhas_da_tabela(linhas, _proxima_tabela(linhas, indice))
                escalacao = [
                    EscalationRow(*(c[:5] + [""] * (5 - len(c))))
                    for c in corpo[1:] if c and c[0]
                ]
                continue
            categoria = ""
            indice += 1
            continue

        if linha.startswith("|"):
            corpo, indice = _linhas_da_tabela(linhas, indice)
            _absorver_tabela(corpo, categoria, por_nome, ordem)
            continue

        indice += 1

    por_time = {normalize_text(l.team): l for l in escalacao}
    for entrada in ordem:
        entrada.escalation = por_time.get(normalize_text(entrada.team))

    return Catalog(
        entries=ordem,
        escalation=escalacao,
        source_path=str(arquivo),
        source_hash=f"sha256:{hashlib.sha256(texto.encode('utf-8')).hexdigest()[:16]}",
    )


def _proxima_tabela(linhas: list[str], depois: int) -> int:
    indice = depois + 1
    while indice < len(linhas) and not linhas[indice].strip().startswith("|"):
        indice += 1
    return indice


def _absorver_tabela(
    corpo: list[list[str]],
    categoria: str,
    por_nome: dict[str, CatalogEntry],
    ordem: list[CatalogEntry],
) -> None:
    """Distribui uma tabela para o campo certo, pelo cabeçalho dela.

    O formato é reconhecido pelo cabeçalho, não pela posição: se alguém colar o
    wiki com as seções fora de ordem, a leitura continua correta.
    """
    if not corpo:
        return
    cabecalho = [normalize_text(c) for c in corpo[0]]
    if not cabecalho or "alerta" not in cabecalho[0]:
        return

    acao = "acao imediata do operador" in cabecalho or len(cabecalho) >= 6
    for celulas in corpo[1:]:
        if not celulas or not celulas[0]:
            continue
        nome = celulas[0]
        chave = normalize_text(nome)
        entrada = por_nome.get(chave)
        if entrada is None:
            entrada = CatalogEntry(id=_entry_id(categoria, nome), name=nome, category=categoria)
            por_nome[chave] = entrada
            ordem.append(entrada)
        if not entrada.category:
            entrada.category = categoria

        if acao:
            icone = _icone(celulas[1] if len(celulas) > 1 else "")
            entrada.severity_icon = icone
            entrada.severity_label = SEVERITY_LABELS.get(icone, "")
            entrada.host = celulas[2] if len(celulas) > 2 else ""
            entrada.action = celulas[3] if len(celulas) > 3 else ""
            entrada.routing_raw = celulas[4] if len(celulas) > 4 else ""
            entrada.team, entrada.channel = parse_routing(entrada.routing_raw)
            entrada.sla = parse_sla(celulas[5] if len(celulas) > 5 else "")
        else:
            entrada.description = celulas[1] if len(celulas) > 1 else ""
            entrada.probable_cause = celulas[2] if len(celulas) > 2 else ""
            referencia = celulas[3] if len(celulas) > 3 else ""
            entrada.reference = "" if referencia in ("-", "—") else referencia


def _icone(celula: str) -> str:
    for icone in SEVERITY_LABELS:
        if icone in celula:
            return icone
    return ""
