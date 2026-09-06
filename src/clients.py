"""De quem é cada alerta.

O Master Support presta NOC para vários clientes. O mesmo alerta técnico
("disco cheio") tem contato, fila e SLA diferentes conforme o dono do host —
então a unidade de organização da wiki é o **cliente**, e a categoria técnica
é a subdivisão.

## Por que não dá para usar o host group

Os grupos do Zabbix são recortes técnicos e misturam clientes: "Ativos de
Rede" tem roteador de operadora e AP de escritório, "Applications" tem
Control-M da Chubb e Grafana de três clientes diferentes. Quem carrega a
informação de dono é o **nome do host** — `Chubb - SQLDB`, `Vibe - Zabbix
server`, `Saq - AWS`. O grupo entra só como último recurso, para os hosts sem
prefixo.

## Ordem importa

`Vibe Crédito Banpará (máquinas)` é host do Banpará, não da Vibe. Se `Vibe*`
fosse avaliado antes, capturaria o host errado e o alerta apareceria na seção
do cliente errado — com o contato errado no plantão. Por isso a resolução
respeita a ordem do arquivo, e os nomes ambíguos vêm primeiro.

## Sem palpite

Host que não casa com ninguém não é chutado para o cliente mais provável:
vira `NAO_CLASSIFICADO` e aparece assim. Um alerta atribuído ao cliente errado
é pior que um alerta sem dono — o primeiro manda o operador acionar quem não
tem nada a ver com aquilo.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_FILE = "clients.json"

#: Host que não casou com nenhum cliente. Fica visível de propósito.
NAO_CLASSIFICADO = "nao-classificado"
NAO_CLASSIFICADO_LABEL = "Não classificado"


@dataclass(frozen=True)
class Client:
    """Um cliente e as regras que dizem quais hosts são dele."""

    id: str
    label: str
    monitored_by_us: bool = True
    note: str = ""
    hosts: tuple[str, ...] = ()
    host_patterns: tuple[str, ...] = ()
    host_groups: tuple[str, ...] = ()

    def matches(self, host_name: str, host_technical: str, groups: tuple[str, ...]) -> bool:
        nomes = [n for n in (host_name, host_technical) if n]

        # 1. nome exato — a regra mais forte, e a única que não depende de
        #    convenção de nomenclatura se manter no futuro.
        exatos = {h.casefold() for h in self.hosts}
        if any(n.casefold() in exatos for n in nomes):
            return True

        # 2. curinga sobre o nome
        for padrao in self.host_patterns:
            if any(fnmatch.fnmatch(n.casefold(), padrao.casefold()) for n in nomes):
                return True

        # 3. host group — último recurso, para host sem prefixo de cliente
        grupos = {g.casefold() for g in self.host_groups}
        return any(g.casefold() in grupos for g in groups)


@dataclass
class ClientRegistry:
    """Os clientes configurados, na ordem em que devem ser avaliados."""

    clients: tuple[Client, ...] = ()
    path: Path | None = None
    #: Cache de host -> id, porque a wiki resolve o mesmo host muitas vezes.
    _cache: dict[tuple[str, str, tuple[str, ...]], str] = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, caminho: str | Path | None = None) -> "ClientRegistry":
        """Lê o arquivo. Sem arquivo, tudo cai em 'Não classificado'.

        Ausência de configuração não pode virar palpite: sem o arquivo, o
        sistema não sabe de quem é nada — e é isso que ele mostra.
        """
        alvo = Path(caminho or DEFAULT_FILE)
        if not alvo.is_file():
            return cls(clients=(), path=alvo)

        try:
            dados = json.loads(alvo.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"clients.json inválido ({alvo}): {exc}") from exc

        clientes = []
        for bruto in dados.get("clients") or []:
            identificador = str(bruto.get("id") or "").strip()
            if not identificador:
                continue
            clientes.append(Client(
                id=identificador,
                label=str(bruto.get("label") or identificador),
                monitored_by_us=bool(bruto.get("monitored_by_us", True)),
                note=str(bruto.get("note") or ""),
                hosts=tuple(bruto.get("hosts") or ()),
                host_patterns=tuple(bruto.get("host_patterns") or ()),
                host_groups=tuple(bruto.get("host_groups") or ()),
            ))
        return cls(clients=tuple(clientes), path=alvo)

    def by_id(self, identificador: str) -> Client | None:
        return next((c for c in self.clients if c.id == identificador), None)

    def label_of(self, identificador: str) -> str:
        cliente = self.by_id(identificador)
        return cliente.label if cliente else NAO_CLASSIFICADO_LABEL

    def resolve(self, host_name: str = "", host_technical: str = "",
                groups: tuple[str, ...] | list[str] = ()) -> str:
        """Devolve o id do cliente dono do host — o PRIMEIRO que casar."""
        chave = (host_name, host_technical, tuple(groups))
        if chave in self._cache:
            return self._cache[chave]

        resultado = NAO_CLASSIFICADO
        for cliente in self.clients:
            if cliente.matches(host_name, host_technical, tuple(groups)):
                resultado = cliente.id
                break

        self._cache[chave] = resultado
        return resultado

    def resolve_alert(self, alerta: dict[str, Any]) -> str:
        """Cliente dono de um alerta normalizado ou do bloco `zabbix` de uma ficha."""
        zbx = alerta.get("zabbix") if "zabbix" in alerta else alerta
        zbx = zbx or {}
        host = zbx.get("host") or {}
        return self.resolve(
            str(host.get("name") or ""),
            str(host.get("host") or ""),
            tuple(zbx.get("host_groups") or ()),
        )

    def is_monitored(self, identificador: str) -> bool:
        """Um cliente que outro NOC atende não entra na wiki de plantão.

        `Não classificado` conta como monitorado: se não sabemos de quem é,
        esconder seria decidir por omissão.
        """
        cliente = self.by_id(identificador)
        return cliente.monitored_by_us if cliente else True
