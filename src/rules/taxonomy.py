"""Categorias operacionais: o que o alerta está monitorando de fato.

## Por que a chave do item, e não a descrição

A pergunta que interessa não é "como o trigger se chama", é "o que ele observa".
E isso está na **chave do item** — que é estrutural, não redigida por humano.

No host real `Vibe - MSTracker-vm Hom` (36 alertas em 29 famílias técnicas), a
chave agrupa sozinha o que a descrição espalharia:

    vfs.fs.*        /: Disk space is low
                    /: Disk space is critically low
                    /: Running out of free inodes
                    /: Filesystem has become read-only
                    /: Pouco espaço em disco        ← em português, mesma coisa
    system.cpu.*    Linux: High CPU utilization
                    Linux: Load average is too high  ← nome bem diferente

Cinco famílias técnicas viram uma unidade operacional; duas descrições sem
nenhuma palavra em comum viram outra. Nenhuma heurística de texto faria isso
com segurança.

## A descrição ainda importa

Ela não é ignorada — é o **segundo** sinal, e o que salva os casos em que a
chave engana. `Interface ens160: Link down` é lido de um item `vfs.file.contents`
(um item calculado), então a chave diria "arquivo" e erraria. A descrição diz
"Interface", e acerta.

Quando os dois sinais concordam, a confiança é alta. Quando só um fala, é
média. Quando nenhum fala, o alerta fica **sem categoria** — e sem categoria
ele não entra em regra nenhuma, porque inventar um agrupamento é pior do que
admitir que não sabemos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..keys import normalize_text


@dataclass(frozen=True)
class Category:
    """Uma categoria operacional — o nível em que o procedimento costuma ser único."""

    id: str
    label: str
    #: Prefixos de chave de item. Sinal ESTRUTURAL: forte e explicável.
    item_prefixes: tuple[str, ...] = ()
    #: Termos na descrição. Sinal TEXTUAL: complementa, nunca decide sozinho
    #: quando a chave já disse outra coisa.
    keywords: tuple[str, ...] = ()
    description: str = ""


#: Taxonomia derivada dos prefixos de item realmente presentes no ambiente
#: coletado — não de um catálogo teórico. Ampliar é seguro: uma categoria nova
#: só muda o agrupamento de quem casar com ela.
CATEGORIES: tuple[Category, ...] = (
    Category(
        "filesystem", "Disco / Filesystem",
        item_prefixes=("vfs.fs",),
        keywords=("disk space", "filesystem", "inode", "espaco em disco", "espaço em disco",
                  "particao", "partição", "read-only", "somente leitura", "mount"),
        description="Espaço, inodes e estado dos sistemas de arquivos.",
    ),
    Category(
        "storage_io", "Disco / Desempenho de I-O",
        item_prefixes=("vfs.dev",),
        keywords=("disk read", "disk write", "request responses", "latencia de disco", "iops"),
        description="Latência e taxa de leitura/escrita dos dispositivos de bloco.",
    ),
    Category(
        "cpu", "CPU / Processamento",
        item_prefixes=("system.cpu", "perf_counter_en"),
        keywords=("cpu", "load average", "processamento", "carga do processador"),
        description="Utilização de CPU e carga do sistema.",
    ),
    Category(
        "memory", "Memória",
        item_prefixes=("vm.memory", "system.swap"),
        keywords=("memory", "memoria", "memória", "swap", "oom"),
        description="Memória disponível, utilização e uso de swap.",
    ),
    Category(
        "network_interface", "Rede / Interfaces",
        item_prefixes=("net.if",),
        keywords=("interface", "link down", "bandwidth", "largura de banda", "ethernet",
                  "error rate", "taxa de erro", "velocidade"),
        description="Estado, erros e utilização das interfaces de rede.",
    ),
    Category(
        "connectivity", "Rede / Conectividade",
        item_prefixes=("icmpping", "icmppingloss", "icmppingsec", "agent.ping", "net.tcp"),
        keywords=("icmp", "ping", "unavailable", "indisponivel", "indisponível", "unreachable"),
        description="Alcançabilidade por ICMP/TCP e disponibilidade básica do host.",
    ),
    Category(
        "vpn", "Rede / VPN e SD-WAN",
        item_prefixes=("vpn.tunnel", "sdwan_health"),
        keywords=("vpn", "tunnel", "sd-wan", "sdwan", "ipsec"),
        description="Túneis de VPN e saúde de links SD-WAN.",
    ),
    Category(
        "agent", "Agente Zabbix",
        item_prefixes=("zabbix", "agent.version"),
        keywords=("zabbix agent", "agente zabbix", "agent is not available"),
        description="Disponibilidade e estado do agente de coleta.",
    ),
    Category(
        "service", "Serviços e processos",
        item_prefixes=("service.info", "proc.num", "service.discovery"),
        keywords=("service", "servico", "serviço", "is not running", "parado", "process limit"),
        description="Serviços do sistema operacional e contagem de processos.",
    ),
    Category(
        "api_web", "APIs e checagens web",
        item_prefixes=("web.test", "check.api", "net.tcp.service.perf"),
        keywords=("api", "http", "endpoint", "web scenario", "indisponivel", "lenta", "timeout"),
        description="Cenários web, endpoints HTTP e verificações de API.",
    ),
    Category(
        "certificate", "Certificados e domínios",
        item_prefixes=("cert.", "domain_check_expiry", "ssl"),
        keywords=("certificad", "certificate", "ssl", "expira", "expiry", "fingerprint", "dominio", "domínio"),
        description="Validade e integridade de certificados TLS e domínios.",
    ),
    Category(
        "job", "Jobs e agendamentos",
        item_prefixes=("job.status", "job."),
        keywords=("job", "ended not ok", "batch", "agendamento", "control-m"),
        description="Execuções agendadas e resultado de jobs.",
    ),
    Category(
        "ticket", "Chamados e filas",
        item_prefixes=("temporestante2", "alerta.", "chamado"),
        keywords=("chamado", "atendimento", "aguardando cliente", "aguardando setor", "defasado", "sla"),
        description="Chamados e filas de atendimento monitorados como itens.",
    ),
    Category(
        "cloud", "Nuvem (AWS/Lambda)",
        item_prefixes=("aws_check.py", "aws."),
        keywords=("lambda", "aws", "sqs", "s3", "rds"),
        description="Recursos e funções em nuvem.",
    ),
    Category(
        "hardware", "Hardware e ambiente",
        item_prefixes=("sensor.temp", "system.hw", "sensor."),
        keywords=("temperatura", "sensor", "fonte", "power supply", "fan", "raid", "idrac"),
        description="Sensores físicos, temperatura e componentes de hardware.",
    ),
    Category(
        "database", "Banco de dados",
        item_prefixes=("mssql", "mysql", "pgsql", "db."),
        keywords=("backup is old", "database", "banco de dados", "buffer cache", "sqldb"),
        description="Bancos de dados, backups e desempenho de instâncias.",
    ),
    Category(
        "security", "Segurança e integridade",
        item_prefixes=("vfs.file.cksum", "onesecure", "wazuh"),
        keywords=("passwd has been changed", "integridade", "siem", "incident", "seguranca", "segurança"),
        description="Integridade de arquivos, SIEM e incidentes de segurança.",
    ),
    Category(
        "system_state", "Sistema operacional",
        item_prefixes=("system.uptime", "system.localtime", "system.sw", "system.hostname",
                       "kernel.max", "system.boottime"),
        keywords=("restarted", "reiniciado", "out of sync", "system name has changed",
                  "operating system", "installed packages", "filedescriptors"),
        description="Reboot, relógio, inventário de software e limites do kernel.",
    ),
    Category(
        "license", "Licenças",
        # `pusado.[X]` / `usados.[X]` são "percentual usado" de LICENÇA, não de
        # disco. O prefixo parece de filesystem e não é: descoberto olhando o
        # ambiente real, depois de o agrupamento colocar "FLOW_FREE" e
        # "Exchange Online" dentro de "Disco / Filesystem".
        item_prefixes=("licenca", "license", "pusado", "usados"),
        keywords=("licenca", "licença", "license", "subscription", "todas as licencas",
                  "todas as licenças"),
        description="Validade e consumo de licenças.",
    ),
)

CATEGORY_BY_ID = {c.id: c for c in CATEGORIES}

#: Categoria de quem não casou com nada. Alertas sem categoria NÃO entram em
#: regra: agrupar o que não se entende é pior do que deixar separado.
UNCATEGORIZED = "uncategorized"
UNCATEGORIZED_LABEL = "Sem categoria identificada"

_SEPARADOR = re.compile(r"[\[\s,]")


def item_prefixes(alerta: dict[str, Any]) -> list[str]:
    """Prefixos das chaves de item do alerta, do mais específico ao mais geral."""
    saida: list[str] = []
    for item in (alerta.get("zabbix") or {}).get("items") or []:
        chave = str(item.get("key_") or "")
        if not chave:
            continue
        base = _SEPARADOR.split(chave)[0]
        partes = base.split(".")
        for tamanho in range(len(partes), 0, -1):
            saida.append(".".join(partes[:tamanho]))
    return saida


@dataclass
class Classification:
    """A categoria escolhida e as evidências que levaram até ela."""

    category_id: str = UNCATEGORIZED
    label: str = UNCATEGORIZED_LABEL
    by_item: bool = False
    by_keyword: bool = False
    evidence: list[str] = field(default_factory=list)

    @property
    def confident(self) -> bool:
        """Os dois sinais independentes concordaram."""
        return self.by_item and self.by_keyword

    @property
    def known(self) -> bool:
        return self.category_id != UNCATEGORIZED


def classify(alerta: dict[str, Any]) -> Classification:
    """Classifica um alerta numa categoria operacional, com as evidências.

    A chave do item decide; a descrição confirma ou desempata. Quando a chave
    não fala e a descrição fala, a categoria vale — com confiança menor.
    """
    prefixos = item_prefixes(alerta)
    zbx = alerta.get("zabbix") or {}
    texto = normalize_text(" ".join(str(t) for t in (
        zbx.get("description_raw", ""),
        zbx.get("prototype_description") or "",
        zbx.get("event_name", ""),
    )))

    por_item: tuple[Category, str] | None = None
    for categoria in CATEGORIES:
        for prefixo in categoria.item_prefixes:
            if prefixo in prefixos or any(p.startswith(prefixo) for p in prefixos):
                por_item = (categoria, prefixo)
                break
        if por_item:
            break

    por_texto: tuple[Category, str] | None = None
    for categoria in CATEGORIES:
        for termo in categoria.keywords:
            if normalize_text(termo) in texto:
                por_texto = (categoria, termo)
                break
        if por_texto:
            break

    if por_item and por_texto and por_item[0].id == por_texto[0].id:
        categoria = por_item[0]
        return Classification(
            categoria.id, categoria.label, by_item=True, by_keyword=True,
            evidence=[f"chave de item começa com `{por_item[1]}`",
                      f"descrição menciona “{por_texto[1]}”"],
        )
    if por_item:
        categoria = por_item[0]
        # A chave venceu a descrição: ela é estrutural, a descrição é redigida
        # à mão e pode falar de outra coisa ("Interface X" lendo um arquivo).
        evidencias = [f"chave de item começa com `{por_item[1]}`"]
        if por_texto:
            evidencias.append(f"descrição sugeriria “{por_texto[0].label}”, mas a chave do item prevalece")
        return Classification(categoria.id, categoria.label, by_item=True, evidence=evidencias)
    if por_texto:
        categoria = por_texto[0]
        return Classification(
            categoria.id, categoria.label, by_keyword=True,
            evidence=[f"descrição menciona “{por_texto[1]}” (nenhuma chave de item conhecida)"],
        )
    return Classification()
