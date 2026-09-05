"""Instância: *onde* a regra está sendo aplicada.

Uma regra de LLD gera um alerta por entidade descoberta. O protótipo diz a
forma; o alerta descoberto diz o valor:

    protótipo   {#FSNAME}: Disk space is critically low
    alerta      /boot: Disk space is critically low
                ↑
                instância = "/boot"

A extração é feita alinhando os dois textos: as macros do protótipo viram
grupos de captura, e o que ocupou o lugar delas é a instância. É determinístico
e reversível — nada é adivinhado a partir do texto solto.

Quando não há protótipo (trigger direto no host), a instância é procurada nos
**parâmetros da chave do item** (`vfs.fs.dependent.size[/boot,pused]` → `/boot`).
Esse caminho é menos exato, então vem marcado com a origem `item_key`: quem lê
sabe de onde veio.

Se nenhum dos dois caminhos produzir um valor, o alerta simplesmente **não tem
instância**. Isso é um estado válido: muita regra se aplica ao host inteiro.
"""

from __future__ import annotations

import re
from typing import Any

#: Macro de LLD no texto do protótipo: `{#FSNAME}`, `{#SERVICE.NAME}`.
_MACRO_LLD = re.compile(r"\{#[A-Z0-9._]+\}", re.IGNORECASE)

#: Parâmetros que são modo/unidade, não entidade descoberta. Sem esta lista,
#: `vfs.fs.dependent.size[/boot,pused]` devolveria "pused" como instância.
_PARAMETROS_IGNORADOS = frozenset({
    "pused", "pfree", "free", "used", "total", "avg", "min", "max", "sum",
    "bps", "pps", "in", "out", "errors", "discovery", "get", "count",
    # Termos genéricos do próprio Zabbix: `zabbix[host,agent,available]` daria
    # uma "instância" chamada `host`, que não identifica coisa nenhuma.
    "host", "agent", "available", "self", "all", "*", "proxy", "server",
})

#: Valores que não identificam nada e só poluiriam a lista de instâncias.
_VALORES_VAZIOS = frozenset({"", "-", "0", "none", "null", "n/a"})

MAX_INSTANCE_LEN = 120


def _limpar(valor: str) -> str:
    return valor.strip().strip("\"'()[]").strip()


def from_prototype(prototype: str, description: str) -> list[str]:
    """Extrai os valores que ocuparam as macros do protótipo.

    `{#FSNAME}: Disk space is low` + `/boot: Disk space is low` -> `["/boot"]`
    """
    if not prototype or not description or not _MACRO_LLD.search(prototype):
        return []

    # O protótipo vira um regex: texto literal escapado, macros como capturas.
    padrao = ""
    posicao = 0
    for macro in _MACRO_LLD.finditer(prototype):
        padrao += re.escape(prototype[posicao:macro.start()])
        padrao += "(.+?)"
        posicao = macro.end()
    padrao += re.escape(prototype[posicao:])

    casamento = re.fullmatch(padrao, description, re.DOTALL)
    if casamento is None:
        return []

    valores: list[str] = []
    for bruto in casamento.groups():
        valor = _limpar(bruto)
        if valor.lower() in _VALORES_VAZIOS or len(valor) > MAX_INSTANCE_LEN:
            continue
        if valor.startswith("{") and valor.endswith("}"):
            # `{#FSLABEL}` que a descoberta não expandiu: é a forma, não a
            # entidade. Tratar como instância criaria uma "instância" chamada
            # macro em toda regra que tivesse um protótipo mal preenchido.
            continue
        if valor not in valores:
            valores.append(valor)
    return valores


def from_item_keys(alerta: dict[str, Any]) -> list[str]:
    """Procura a entidade nos parâmetros das chaves de item."""
    valores: list[str] = []
    for item in (alerta.get("zabbix") or {}).get("items") or []:
        chave = str(item.get("key_") or "")
        if "[" not in chave or not chave.endswith("]"):
            continue
        argumentos = chave[chave.index("[") + 1: -1]
        for bruto in argumentos.split(","):
            valor = _limpar(bruto)
            if not valor or valor.lower() in _PARAMETROS_IGNORADOS or valor.lower() in _VALORES_VAZIOS:
                continue
            if valor.startswith("{") or len(valor) > MAX_INSTANCE_LEN:
                continue  # macro não expandida não é instância
            if valor not in valores:
                valores.append(valor)
            break  # o primeiro parâmetro útil é a entidade; o resto é modo
    return valores


def instance_of(alerta: dict[str, Any]) -> dict[str, Any] | None:
    """A instância de um alerta, com a origem declarada.

    Devolve `None` quando a regra se aplica ao host inteiro — estado válido,
    não falha de extração.
    """
    zbx = alerta.get("zabbix") or {}
    prototipo = zbx.get("prototype_description") or ""
    descricao = zbx.get("description_raw") or ""

    valores = from_prototype(prototipo, descricao)
    if valores:
        return {"name": valores[0], "values": valores, "source": "prototype",
                "evidence": f"protótipo `{prototipo}` casado com a descrição do alerta"}

    valores = from_item_keys(alerta)
    if valores:
        return {"name": valores[0], "values": valores, "source": "item_key",
                "evidence": f"parâmetro da chave de item `{valores[0]}`"}

    return None
