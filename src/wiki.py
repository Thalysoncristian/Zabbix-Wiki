"""ETAPA 10 — a wiki gerada a partir das fichas validadas.

    docs/alerts/*.json  ──>  wiki.md  ──>  Wiki.js do NOC

## Por que gerar, e não escrever à mão

A wiki escrita à mão não tem como saber que envelheceu. Quando um trigger é
recriado, renomeado ou apagado no Zabbix, a página continua idêntica e
convincente — e alguém às 3h segue um procedimento para um alerta que não
existe mais. A ficha sabe: ela carrega `alert_key`, `source_hash` e o estado
`review_needed` que o `reconcile` levanta quando o fato técnico muda.

Este módulo é a ponte entre as duas coisas. O conhecimento continua sendo
escrito por pessoas, nas fichas; a página é uma projeção.

## O que entra

**Somente fichas `documented` ou `reviewed`.** Rascunho não entra, nem
marcado como rascunho: numa página de plantão, texto que parece procedimento
é lido como procedimento. Quem quiser ver o que ainda falta usa a interface
local, que separa os estados com clareza.

## Dialeto

Wiki.js — o mesmo do catálogo que o NOC já mantém (`{.is-warning}`,
`{.tabset}`, `<details>`). O objetivo é que a página gerada seja
indistinguível, no formato, da que existe hoje; o que muda é a origem.

A saída é **determinística**: mesma entrada, mesmos bytes. Sem isso não dá
para versionar o resultado nem enxergar num diff o que mudou de uma geração
para outra.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .clients import NAO_CLASSIFICADO, ClientRegistry
from .core.models import SCOPE_MANUAL
from .core.repository import AlertRepository
from .core.status import DOCUMENTED_STATUSES
from .rules.taxonomy import CATEGORY_BY_ID, UNCATEGORIZED, classify

#: Ícone por severidade, no padrão que o catálogo do NOC já usa.
ICONE_SEVERIDADE = {
    "Disaster": "🔴",
    "High": "🟠",
    "Average": "🟡",
    "Warning": "🟡",
    "Information": "🔵",
    "Not classified": "⚪",
}

#: Seção das fichas que não vêm de trigger nenhum. Fica separada de propósito:
#: o operador precisa saber que ali o Zabbix não avisa — quem avisa é o
#: sistema de origem, por e-mail ou webhook.
SECAO_MANUAL = "Fora do Zabbix"

#: Ordem das seções. Categorias fora desta lista entram depois, em ordem
#: alfabética; a seção manual é sempre a última.
ORDEM_SECOES = (
    "connectivity", "network_interface", "vpn", "filesystem", "storage_io",
    "cpu", "memory", "system_state", "agent", "service", "api_web",
    "database", "certificate", "license", "security", "job", "ticket",
    "hardware", "cloud", "printer",
)


def _celula(texto: Any) -> str:
    """Deixa um valor seguro para uma célula de tabela Markdown."""
    if texto is None:
        return "—"
    if isinstance(texto, (list, tuple)):
        texto = " · ".join(str(t) for t in texto if str(t).strip())
    texto = str(texto).strip()
    if not texto:
        return "—"
    # `|` fecharia a célula; quebra de linha fecharia a tabela inteira.
    return texto.replace("|", "\\|").replace("\n", " ")


def _lista(valor: Any) -> list[str]:
    if isinstance(valor, (list, tuple)):
        return [str(v).strip() for v in valor if str(v).strip()]
    texto = str(valor or "").strip()
    return [texto] if texto else []


@dataclass
class Entrada:
    """Uma linha da wiki: um procedimento e os alertas que ele cobre."""

    titulo: str
    operacional: dict[str, Any]
    categoria: str
    #: Id do cliente dono dos alertas. A wiki abre por aqui: o mesmo "disco
    #: cheio" tem contato e SLA diferentes conforme o dono do host.
    cliente: str = NAO_CLASSIFICADO
    alertas: list[str] = field(default_factory=list)
    hosts: list[str] = field(default_factory=list)
    severidades: list[str] = field(default_factory=list)
    manual: bool = False

    @property
    def severidade(self) -> str:
        """A severidade mais grave entre os alertas cobertos."""
        for nome in ("Disaster", "High", "Average", "Warning", "Information", "Not classified"):
            if nome in self.severidades:
                return nome
        return "Not classified"

    @property
    def icone(self) -> str:
        return ICONE_SEVERIDADE.get(self.severidade, "⚪")

    @property
    def sla(self) -> str:
        """SLA em texto. Sai do que a pessoa escreveu, nunca é calculado."""
        escalonamento = self.operacional.get("escalation") or {}
        minutos = escalonamento.get("after_minutes")
        if minutos:
            return f"{minutos} min"
        if self.operacional.get("requires_ticket"):
            return "Imediato"
        return "—"

    @property
    def fila(self) -> str:
        rota = self.operacional.get("routing") or {}
        time = str(rota.get("team") or "").strip()
        canal = str(rota.get("ticket_queue") or rota.get("channel") or "").strip()
        if time and canal:
            return f"{time} · {canal}"
        return time or canal or "—"


def _titulo_do_alerta(doc: Any) -> str:
    """Como o alerta aparece para o operador no Zabbix."""
    zbx = doc.zabbix or {}
    return str(
        zbx.get("prototype_description")
        or zbx.get("description_raw")
        or (doc.operational or {}).get("title")
        or doc.alert_key
    )


def _assinatura(operacional: dict[str, Any]) -> str:
    """Identidade do PROCEDIMENTO, ignorando o título.

    Oito famílias de endpoint ENEL receberam o mesmo procedimento — e numa
    página de consulta isso vira oito entradas idênticas, que o operador lê
    como oito casos diferentes. Aqui elas viram uma entrada com os oito
    alertas listados.
    """
    interessa = {
        chave: valor for chave, valor in sorted(operacional.items())
        if chave not in ("title", "reviewed_by", "reviewed_at", "last_zabbix_hash_at_review")
    }
    return json.dumps(interessa, sort_keys=True, ensure_ascii=False)


def coletar_entradas(docs_dir: str | Path,
                     registry: ClientRegistry | None = None) -> list[Entrada]:
    """Lê as fichas validadas e agrupa as que compartilham procedimento.

    O agrupamento é por `(cliente, procedimento)`, não só por procedimento:
    dois clientes podem ter o mesmo texto técnico e ainda assim precisam de
    entradas separadas, porque o contato e o SLA são de quem é o host.
    """
    registry = registry or ClientRegistry.load()
    por_assinatura: dict[tuple[str, str], Entrada] = {}

    for doc in AlertRepository(docs_dir).all():
        operacional = doc.operational or {}
        if operacional.get("doc_status") not in DOCUMENTED_STATUSES:
            continue

        manual = doc.scope == SCOPE_MANUAL
        zbx = doc.zabbix or {}
        if manual:
            categoria = SECAO_MANUAL
            # Sem host não há como resolver o dono pelo nome. A ficha pode
            # declarar `client` explicitamente; sem isso fica não classificada
            # — chutar o cliente mandaria o operador acionar quem não tem nada
            # a ver com o alerta.
            cliente = str(operacional.get("client") or NAO_CLASSIFICADO)
        else:
            classificacao = classify({"zabbix": zbx})
            categoria = (
                CATEGORY_BY_ID[classificacao.category_id].label
                if classificacao.category_id != UNCATEGORIZED
                else "Outros"
            )
            cliente = str(operacional.get("client") or registry.resolve_alert({"zabbix": zbx}))

        chave = (cliente, _assinatura(operacional))
        entrada = por_assinatura.get(chave)
        if entrada is None:
            entrada = Entrada(
                titulo=str(operacional.get("title") or doc.alert_key),
                operacional=operacional,
                categoria=categoria,
                cliente=cliente,
                manual=manual,
            )
            por_assinatura[chave] = entrada

        if manual:
            entrada.alertas.append(str(operacional.get("title") or doc.alert_key))
        else:
            entrada.alertas.append(_titulo_do_alerta(doc))
            host = (zbx.get("host") or {}).get("name")
            if host and host not in entrada.hosts:
                entrada.hosts.append(str(host))
            severidade = (zbx.get("priority") or {}).get("name")
            if severidade:
                entrada.severidades.append(str(severidade))

    for entrada in por_assinatura.values():
        entrada.alertas = sorted(set(entrada.alertas))
        entrada.hosts.sort()

    return sorted(por_assinatura.values(), key=lambda e: (e.cliente, e.categoria, e.titulo))


def _ordem_secao(nome: str) -> tuple[int, str]:
    if nome == SECAO_MANUAL:
        return (len(ORDEM_SECOES) + 2, nome)
    rotulos = {CATEGORY_BY_ID[c].label: i for i, c in enumerate(ORDEM_SECOES) if c in CATEGORY_BY_ID}
    return (rotulos.get(nome, len(ORDEM_SECOES) + 1), nome)


def _tabela_acao_rapida(entradas: list[Entrada]) -> list[str]:
    linhas = [
        '<div style="width: 100%; overflow-x: auto;">',
        "",
        "| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |",
        "| :--- | :---: | :--- | :--- | :--- | :--- |",
    ]
    for entrada in entradas:
        acoes = _lista(entrada.operacional.get("actions"))
        primeira = acoes[0] if acoes else _lista(entrada.operacional.get("checks_before_action"))
        linhas.append(
            f"| {_celula(entrada.titulo)} "
            f"| {entrada.icone} "
            f"| {_celula(entrada.hosts or ('—' if not entrada.manual else 'fora do Zabbix'))} "
            f"| {_celula(primeira)} "
            f"| {_celula(entrada.fila)} "
            f"| ⏱️ {_celula(entrada.sla)} |"
        )
    linhas.extend(["", "</div>", ""])
    return linhas


def _referencia_tecnica(secao: str, entradas: list[Entrada]) -> list[str]:
    linhas = [
        "<details>",
        f"<summary>🔍 <strong>Referência técnica — {secao}</strong></summary>",
        "",
        "| Alerta | O que significa | Causa provável | Verificações antes de agir |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for entrada in entradas:
        linhas.append(
            f"| {_celula(entrada.titulo)} "
            f"| {_celula(entrada.operacional.get('meaning'))} "
            f"| {_celula(entrada.operacional.get('probable_cause'))} "
            f"| {_celula(_lista(entrada.operacional.get('checks_before_action')))} |"
        )
    linhas.extend(["", "</details>", ""])
    return linhas


def _detalhe_do_procedimento(entrada: Entrada) -> list[str]:
    """O procedimento inteiro, para quem precisa de mais que a linha da tabela."""
    linhas = [f"##### {entrada.icone} {entrada.titulo}", ""]

    objetivo = str(entrada.operacional.get("objective") or "").strip()
    if objetivo:
        linhas.extend([objetivo, ""])

    if len(entrada.alertas) > 1:
        linhas.append(f"**Cobre {len(entrada.alertas)} alertas:**")
        linhas.extend(f"* `{alerta}`" for alerta in entrada.alertas)
        linhas.append("")

    for rotulo, campo in (("Sintomas", "symptoms"),
                          ("Verificações antes de agir", "checks_before_action"),
                          ("Ações", "actions"),
                          ("Riscos e ressalvas", "risks")):
        itens = _lista(entrada.operacional.get(campo))
        if itens:
            linhas.append(f"**{rotulo}:**")
            linhas.extend(f"* {item}" for item in itens)
            linhas.append("")

    for rotulo, campo in (("Como validar", "validation"),
                          ("Critério de resolução", "resolution_criteria"),
                          ("Observações", "notes")):
        texto = str(entrada.operacional.get(campo) or "").strip()
        if texto:
            linhas.extend([f"**{rotulo}:** {texto}", ""])

    evidencias = _lista(entrada.operacional.get("evidence_required"))
    if evidencias:
        linhas.append("**Evidências obrigatórias no chamado:** " + " · ".join(evidencias))
        linhas.append("")

    return linhas


def _matriz_de_acionamento(entradas: list[Entrada]) -> list[str]:
    """Times e canais, montados a partir do que as fichas realmente dizem.

    Escrita à mão, a matriz descola das fichas com o tempo: alguém muda a fila
    numa e esquece da outra. Derivando daqui, as duas nunca discordam.
    """
    por_time: dict[str, dict[str, Any]] = {}
    for entrada in entradas:
        rota = entrada.operacional.get("routing") or {}
        time = str(rota.get("team") or "").strip()
        if not time:
            continue
        registro = por_time.setdefault(time, {"canais": set(), "escalonamento": set(), "alertas": 0})
        canal = str(rota.get("ticket_queue") or rota.get("channel") or "").strip()
        if canal:
            registro["canais"].add(canal)
        escalonamento = entrada.operacional.get("escalation") or {}
        para = str(escalonamento.get("to") or "").strip()
        if para:
            registro["escalonamento"].add(para)
        registro["alertas"] += len(entrada.alertas)

    linhas = [
        "| Fila / Time | Canal | Escalonamento | Alertas cobertos |",
        "| :--- | :--- | :--- | ---: |",
    ]
    for time in sorted(por_time):
        registro = por_time[time]
        linhas.append(
            f"| **{_celula(time)}** "
            f"| {_celula(sorted(registro['canais']))} "
            f"| {_celula(sorted(registro['escalonamento']))} "
            f"| {registro['alertas']} |"
        )
    linhas.append("")
    return linhas


CABECALHO = """# 📘 Catálogo de Alertas — NOC

Guia operacional para **triagem, abertura de chamado e acionamento correto**
dos alertas monitorados. Cada categoria traz uma tabela de ação rápida, a
referência técnica completa e o procedimento detalhado.

> **Regra de ouro:** nenhum acionamento por Teams ou telefone acontece sem
> **chamado aberto** e **evidência coletada** (host, horário, print/output).
> O SLA só começa a contar depois do chamado registrado.
{.is-warning}

> **Esta página é gerada.** O conteúdo vem das fichas validadas em
> `docs/alerts/` do repositório Zabbix-Wiki — não edite aqui, edite a ficha e
> gere de novo (`python main.py wiki`). Assim a página nunca diverge do que o
> time aprovou, e envelhece junto com o Zabbix em vez de envelhecer sozinha.
{.is-info}
"""

FLUXO = """## ⚡ Fluxo de atendimento

```mermaid
flowchart TD
    A["🔔 Alerta recebido"] --> B{"Severidade"}
    B -->|"🔵 Baixa / 🟡 Média"| C["Aguardar a tolerância do alerta"]
    B -->|"🟠 Alta / 🔴 Crítica"| D["Validar imediatamente"]
    C --> E{"Normalizou sozinho?"}
    E -->|"Sim"| F["Registrar no plantão e encerrar"]
    E -->|"Não"| D
    D --> G["Coletar evidências<br/>host, data e hora, print, output"]
    G --> H["Abrir chamado no DeskManager"]
    H --> I["Transferir para a fila responsável"]
    I --> J{"Houve retorno dentro do SLA?"}
    J -->|"Sim"| K["Acompanhar até a normalização"]
    J -->|"Não"| L["Escalonar<br/>Teams ou telefone do sobreaviso"]
```

## 🎚️ Severidade

| Ícone | Severidade | Postura esperada |
| :---: | :--- | :--- |
| 🔴 | **Crítica** (Disaster) | Validar e abrir chamado na hora. Comunicar o plantão. |
| 🟠 | **Alta** (High) | Validar e abrir chamado na hora. |
| 🟡 | **Média** (Average/Warning) | Respeitar a tolerância do alerta antes de abrir. |
| 🔵 | **Baixa** (Information) | Registrar e transferir sem urgência. |

> **Como ler o SLA:** `7 min` é o tempo de tolerância **mais** a espera pelo
> retorno do chamado antes de escalonar. `Imediato` significa abrir o chamado
> assim que o alerta for validado.
{.is-info}
"""


def _bloco_do_cliente(registry: ClientRegistry, cliente_id: str,
                      entradas: list[Entrada]) -> list[str]:
    """A seção de um cliente: matriz própria e o catálogo por categoria."""
    cliente = registry.by_id(cliente_id)
    rotulo = registry.label_of(cliente_id)
    hosts = sorted({h for e in entradas for h in e.hosts})
    alertas = sum(len(e.alertas) for e in entradas)

    bloco = [f"### {rotulo}\n"]
    resumo = f"**{alertas} alerta(s)** em {len(entradas)} procedimento(s)"
    if hosts:
        resumo += f" · {len(hosts)} host(s): " + ", ".join(f"`{h}`" for h in hosts[:8])
        if len(hosts) > 8:
            resumo += f" e mais {len(hosts) - 8}"
    bloco.extend([resumo, ""])

    if cliente_id == NAO_CLASSIFICADO:
        bloco.append(
            "> Estes alertas não foram atribuídos a nenhum cliente. Não é erro de\n"
            "> coleta: é configuração faltando em `clients.json`. Atribuir por palpite\n"
            "> mandaria o operador acionar quem não tem nada a ver com o alerta.\n"
            "{.is-warning}\n"
        )
    elif cliente and cliente.note:
        bloco.extend([f"> {cliente.note}\n{{.is-info}}\n"])

    bloco.append("#### ☎️ Acionamento\n")
    bloco.extend(_matriz_de_acionamento(entradas))

    por_categoria: dict[str, list[Entrada]] = {}
    for entrada in entradas:
        por_categoria.setdefault(entrada.categoria, []).append(entrada)

    for secao, itens in sorted(por_categoria.items(), key=lambda kv: _ordem_secao(kv[0])):
        bloco.append(f"#### {secao}\n")
        if secao == SECAO_MANUAL:
            bloco.append(
                "> Estes alertas **não vêm do Zabbix**: quem avisa é o próprio sistema de "
                "origem, por e-mail ou webhook. Não espere encontrá-los no painel.\n"
                "{.is-warning}\n"
            )
        bloco.extend(_tabela_acao_rapida(itens))
        bloco.extend(_referencia_tecnica(secao, itens))
        for entrada in itens:
            bloco.extend(_detalhe_do_procedimento(entrada))

    return bloco


def gerar_wiki(docs_dir: str | Path = "docs/alerts", *, gerado_em: str | None = None,
               clients_file: str | Path | None = None) -> str:
    """Monta a página inteira. Determinística: mesma entrada, mesmos bytes.

    A wiki abre por **cliente** porque é assim que o plantão funciona: o mesmo
    "disco cheio" tem contato, fila e SLA diferentes conforme o dono do host.
    Cliente atendido por outro NOC fica de fora — procedimento que não é nosso
    só atrapalha quem está de plantão.
    """
    registry = ClientRegistry.load(clients_file)
    entradas = coletar_entradas(docs_dir, registry)

    de_fora = [e for e in entradas if not registry.is_monitored(e.cliente)]
    entradas = [e for e in entradas if registry.is_monitored(e.cliente)]

    por_cliente: dict[str, list[Entrada]] = {}
    for entrada in entradas:
        por_cliente.setdefault(entrada.cliente, []).append(entrada)

    #: Ordem: por volume de alertas, com o não classificado sempre por último,
    #: para não abrir a página com o que não se sabe.
    def ordem(item: tuple[str, list[Entrada]]) -> tuple[int, int, str]:
        cliente_id, itens = item
        return (1 if cliente_id == NAO_CLASSIFICADO else 0,
                -sum(len(e.alertas) for e in itens),
                registry.label_of(cliente_id))

    partes: list[str] = [CABECALHO, FLUXO]

    if entradas:
        partes.append(
            "## 🏢 Clientes\n\n"
            "| Cliente | Procedimentos | Alertas | Hosts |\n| :--- | ---: | ---: | ---: |\n"
            + "\n".join(
                f"| **{_celula(registry.label_of(cid))}** | {len(itens)} "
                f"| {sum(len(e.alertas) for e in itens)} "
                f"| {len({h for e in itens for h in e.hosts})} |"
                for cid, itens in sorted(por_cliente.items(), key=ordem)
            )
            + "\n"
        )

        partes.append("## 📋 Catálogo por cliente {.tabset}\n")
        for cliente_id, itens in sorted(por_cliente.items(), key=ordem):
            partes.append("\n".join(_bloco_do_cliente(registry, cliente_id, itens)))
    else:
        partes.append(
            "> Nenhuma ficha validada ainda. Documente um procedimento em "
            "`python main.py serve` e gere a página de novo.\n{.is-danger}\n"
        )

    carimbo = gerado_em or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    total_alertas = sum(len(e.alertas) for e in entradas)
    rodape = (
        "---\n\n"
        f"Gerado em {carimbo} · {len(entradas)} procedimento(s) validado(s) "
        f"cobrindo {total_alertas} alerta(s) em {len(por_cliente)} cliente(s) · "
        "fonte: `docs/alerts/` do Zabbix-Wiki."
    )
    if de_fora:
        clientes_fora = sorted({registry.label_of(e.cliente) for e in de_fora})
        rodape += (f"\n\nFora desta página, por serem atendidos por outro NOC: "
                   f"{', '.join(clientes_fora)}.")
    partes.append(rodape + "\n")

    return "\n".join(partes).replace("\n\n\n", "\n\n").rstrip() + "\n"


def escrever_wiki(destino: str | Path, docs_dir: str | Path = "docs/alerts",
                  *, gerado_em: str | None = None,
                  clients_file: str | Path | None = None) -> tuple[Path, int]:
    """Grava a página e devolve `(caminho, procedimentos_publicados)`."""
    conteudo = gerar_wiki(docs_dir, gerado_em=gerado_em, clients_file=clients_file)
    caminho = Path(destino)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding="utf-8")

    registry = ClientRegistry.load(clients_file)
    publicados = [e for e in coletar_entradas(docs_dir, registry)
                  if registry.is_monitored(e.cliente)]
    return caminho, len(publicados)
