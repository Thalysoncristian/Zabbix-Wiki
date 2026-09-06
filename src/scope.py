"""Escopo operacional: o que o NOC analisa, dentro do que foi coletado.

## O problema que isto resolve

A coleta real trouxe 18.903 alertas. Um único host — `Control-M PRD Votorantim`
— responde por cerca de 86% deles, quase todos gerados por LLD, incluindo duas
famílias de ~8.131 alertas cada. Esse host não está sob responsabilidade do NOC
hoje, mas domina todos os indicadores: o dashboard vira um retrato do Control-M
com o resto do ambiente como ruído de fundo.

## Coleta ≠ escopo

São duas coisas diferentes e o sistema as mantém separadas:

    ambiente coletado    o que existe no Zabbix e está no snapshot (18.903)
    escopo operacional   o recorte que o NOC analisa hoje    (~2.577)

O escopo **não altera o snapshot**. Ele nunca apaga, nunca deixa de coletar,
nunca reescreve nada em disco. É uma projeção de leitura, e trocar de escopo é
reversível a qualquer momento — basta trocar o parâmetro.

O escopo também **não é segurança**. Não é autorização, não esconde dado de
ninguém: qualquer pessoa com acesso à interface pode trocar para o ambiente
inteiro em um clique. É classificação operacional, e a interface diz sempre
quanto ficou de fora.

## Exclusão, não inclusão — e por quê

Um escopo pode ser definido de duas formas, e a escolha tem consequência
operacional real:

    lista de inclusão   "o NOC vê APENAS estes hosts"
    lista de exclusão   "o NOC vê tudo, MENOS estes hosts"

Com inclusão, um host novo adicionado ao Zabbix amanhã **não aparece** para o
NOC. Ninguém é avisado. Um host de produção pode ficar meses invisível porque
alguém esqueceu de atualizar uma lista — e a falha é silenciosa, que é o pior
tipo.

Com exclusão, o host novo aparece por padrão. O pior caso é ruído visível, que
alguém nota e trata. Por isso o escopo `noc` usa exclusão.

`include_hosts` existe na configuração para escopos de investigação ("só o
Control-M", "só o Cliente X"), onde a lista fechada É a intenção. Não use
inclusão na visão principal de quem está de plantão.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Escopo sempre disponível: o ambiente inteiro, sem nenhum filtro.
ALL_SCOPE_ID = "all"
ALL_SCOPE_LABEL = "Ambiente inteiro"

#: Arquivo de configuração dos escopos, na raiz do projeto.
DEFAULT_SCOPES_FILE = "scopes.json"


class ScopeError(ValueError):
    """Configuração de escopo inválida."""


@dataclass(frozen=True)
class OperationalScope:
    """Um recorte operacional do ambiente coletado.

    A decisão de pertencimento é sempre tomada no **host** do alerta, nunca no
    host group. Um host pertence a vários grupos, então filtrar por grupo
    esconderia (ou traria) alertas por tabela — os grupos são derivados dos
    hosts que sobraram, não o contrário.
    """

    id: str = ALL_SCOPE_ID
    label: str = ALL_SCOPE_LABEL
    description: str = ""
    exclude_hosts: tuple[str, ...] = ()
    exclude_host_patterns: tuple[str, ...] = ()
    include_hosts: tuple[str, ...] = ()
    include_host_patterns: tuple[str, ...] = ()
    #: Pares `(host, regra de LLD)` a esconder — o recorte fino, quando excluir
    #: o host inteiro é grosso demais. Ver `includes_alert`.
    exclude_discovery_rules: tuple[tuple[str, str], ...] = ()

    @property
    def is_everything(self) -> bool:
        """`True` quando o escopo não filtra nada."""
        return not (self.exclude_hosts or self.exclude_host_patterns
                    or self.include_hosts or self.include_host_patterns
                    or self.exclude_discovery_rules)

    @property
    def mode(self) -> str:
        if self.include_hosts or self.include_host_patterns:
            return "include"
        if self.exclude_hosts or self.exclude_host_patterns or self.exclude_discovery_rules:
            return "exclude"
        return "everything"

    def includes_alert(self, alerta: dict[str, Any]) -> bool:
        """O alerta está no escopo? Decide por host e, depois, por regra de LLD.

        Excluir só por host é grosso demais em um caso real: o host
        `Control-M PRD Votorantim` tem 16.262 alertas de job — que o NOC não
        analisa, porque a malha é acompanhada no próprio Control-M — e 60
        alertas de agente fora, que o NOC **atende** e tem procedimento
        escrito. Tirar o host inteiro escondia os 60 junto com os 16 mil.

        A regra de descoberta separa os dois sem precisar listar alerta por
        alerta: `Jobs` sai, `Agent discovery` fica.
        """
        zbx = alerta.get("zabbix") or {}
        host = zbx.get("host") or {}
        if not self.includes_host(str(host.get("name") or ""), str(host.get("host") or "")):
            return False

        if not self.exclude_discovery_rules:
            return True

        regra = str(((zbx.get("discovery_rule") or {}).get("name")) or "")
        if not regra:
            # Alerta que não veio de LLD não é alcançado por esta regra: ela
            # fala de descoberta, e ele não foi descoberto.
            return True

        nomes = [n for n in (host.get("name"), host.get("host")) if n]
        for host_padrao, regra_padrao in self.exclude_discovery_rules:
            casa_host = any(
                nome.strip().casefold() == host_padrao.strip().casefold()
                or fnmatch.fnmatch(nome, host_padrao)
                for nome in nomes
            )
            casa_regra = (regra.strip().casefold() == regra_padrao.strip().casefold()
                          or fnmatch.fnmatch(regra, regra_padrao))
            if casa_host and casa_regra:
                return False
        return True

    def includes_host(self, *names: str) -> bool:
        """O host está no escopo?

        Recebe os nomes conhecidos do host (visível e técnico) porque o Zabbix
        distingue os dois e o operador digita o que vê na tela.
        """
        conhecidos = [n for n in names if n]
        if not conhecidos:
            # Alerta sem host resolvido: fica no escopo. Sumir em silêncio é
            # pior do que aparecer sem endereço.
            return True

        if self.include_hosts or self.include_host_patterns:
            return any(self._casa(nome, self.include_hosts, self.include_host_patterns) for nome in conhecidos)

        return not any(self._casa(nome, self.exclude_hosts, self.exclude_host_patterns) for nome in conhecidos)

    @staticmethod
    def _casa(nome: str, exatos: tuple[str, ...], padroes: tuple[str, ...]) -> bool:
        # Nome exato é comparado sem diferenciar caixa (quem digita não deve
        # errar por causa de uma maiúscula), mas nunca por "contém": excluir
        # "Control-M PRD" jamais pode derrubar "Control-M PRD 2" sem que
        # alguém tenha escrito um padrão dizendo isso.
        alvo = nome.strip().casefold()
        if any(alvo == e.strip().casefold() for e in exatos):
            return True
        return any(fnmatch.fnmatch(nome, padrao) for padrao in padroes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "mode": self.mode,
            "is_everything": self.is_everything,
            "exclude_hosts": list(self.exclude_hosts),
            "exclude_host_patterns": list(self.exclude_host_patterns),
            "include_hosts": list(self.include_hosts),
            "include_host_patterns": list(self.include_host_patterns),
            "exclude_discovery_rules": [
                {"host": host, "rule": regra} for host, regra in self.exclude_discovery_rules
            ],
        }


#: O escopo do ambiente inteiro, sempre presente e nunca configurável.
EVERYTHING = OperationalScope()


@dataclass
class ScopeConfig:
    """Os escopos disponíveis e qual deles é o padrão."""

    scopes: dict[str, OperationalScope] = field(default_factory=dict)
    default_id: str = ALL_SCOPE_ID
    source: str = ""

    def get(self, scope_id: str | None) -> OperationalScope:
        """Resolve um id de escopo. Vazio devolve o padrão."""
        if not scope_id:
            return self.scopes.get(self.default_id, EVERYTHING)
        escopo = self.scopes.get(scope_id)
        if escopo is None:
            raise ScopeError(
                f"Escopo desconhecido: {scope_id!r}. Disponíveis: {', '.join(sorted(self.scopes))}"
            )
        return escopo

    def listar(self) -> list[dict[str, Any]]:
        ordenados = sorted(
            self.scopes.values(),
            key=lambda e: (e.id != self.default_id, e.id == ALL_SCOPE_ID, e.label.lower()),
        )
        return [{**e.to_dict(), "is_default": e.id == self.default_id} for e in ordenados]


def _tupla(valor: Any, campo: str, escopo: str) -> tuple[str, ...]:
    if valor is None:
        return ()
    if not isinstance(valor, list) or any(not isinstance(v, str) for v in valor):
        raise ScopeError(f"Escopo {escopo!r}: '{campo}' precisa ser uma lista de textos.")
    return tuple(v for v in valor if v.strip())


def _regras_de_descoberta(valor: Any, escopo: str) -> tuple[tuple[str, str], ...]:
    """Lê `exclude_discovery_rules`: pares `{host, rule}`.

    Exige os dois campos de propósito. Uma regra sem host valeria para o
    ambiente inteiro — e `Jobs` é um nome de LLD genérico o bastante para
    existir em vários clientes, então uma exclusão global esconderia coisa de
    quem ninguém mandou esconder.
    """
    if valor is None:
        return ()
    if not isinstance(valor, list):
        raise ScopeError(f"Escopo {escopo!r}: 'exclude_discovery_rules' precisa ser uma lista.")

    pares: list[tuple[str, str]] = []
    for item in valor:
        if not isinstance(item, dict):
            raise ScopeError(
                f"Escopo {escopo!r}: cada item de 'exclude_discovery_rules' precisa ser "
                "um objeto com 'host' e 'rule'."
            )
        host = str(item.get("host") or "").strip()
        regra = str(item.get("rule") or "").strip()
        if not host or not regra:
            raise ScopeError(
                f"Escopo {escopo!r}: 'exclude_discovery_rules' exige 'host' e 'rule' "
                "preenchidos — uma regra sem host esconderia alertas de outros clientes."
            )
        pares.append((host, regra))
    return tuple(pares)


def parse_scopes(payload: dict[str, Any], source: str = "") -> ScopeConfig:
    """Constrói a configuração a partir do dicionário do `scopes.json`."""
    if not isinstance(payload, dict):
        raise ScopeError("scopes.json precisa conter um objeto JSON.")

    escopos: dict[str, OperationalScope] = {ALL_SCOPE_ID: EVERYTHING}

    for bruto in payload.get("scopes") or []:
        if not isinstance(bruto, dict):
            raise ScopeError("Cada escopo precisa ser um objeto JSON.")
        identificador = str(bruto.get("id") or "").strip()
        if not identificador:
            raise ScopeError("Escopo sem 'id'.")
        if identificador == ALL_SCOPE_ID:
            raise ScopeError(f"'{ALL_SCOPE_ID}' é reservado para o ambiente inteiro.")

        escopo = OperationalScope(
            id=identificador,
            label=str(bruto.get("label") or identificador),
            description=str(bruto.get("description") or ""),
            exclude_hosts=_tupla(bruto.get("exclude_hosts"), "exclude_hosts", identificador),
            exclude_host_patterns=_tupla(bruto.get("exclude_host_patterns"), "exclude_host_patterns", identificador),
            include_hosts=_tupla(bruto.get("include_hosts"), "include_hosts", identificador),
            include_host_patterns=_tupla(bruto.get("include_host_patterns"), "include_host_patterns", identificador),
            exclude_discovery_rules=_regras_de_descoberta(bruto.get("exclude_discovery_rules"), identificador),
        )
        if escopo.mode == "include" and (escopo.exclude_hosts or escopo.exclude_host_patterns):
            raise ScopeError(
                f"Escopo {identificador!r}: misturar inclusão e exclusão torna o resultado ambíguo. "
                "Use um dos dois."
            )
        escopos[identificador] = escopo

    padrao = str(payload.get("default") or ALL_SCOPE_ID)
    if padrao not in escopos:
        raise ScopeError(f"'default' aponta para um escopo inexistente: {padrao!r}")

    return ScopeConfig(scopes=escopos, default_id=padrao, source=source)


def load_scopes(caminho: str | Path | None = None) -> ScopeConfig:
    """Lê `scopes.json`. Sem arquivo, existe apenas o ambiente inteiro.

    A ausência do arquivo é um estado válido e silencioso: quem nunca precisou
    de escopo continua vendo tudo, como antes.
    """
    alvo = Path(caminho or DEFAULT_SCOPES_FILE)
    if not alvo.is_file():
        return ScopeConfig(scopes={ALL_SCOPE_ID: EVERYTHING}, default_id=ALL_SCOPE_ID, source="")
    try:
        payload = json.loads(alvo.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScopeError(f"{alvo} não é um JSON válido: {exc}") from exc
    return parse_scopes(payload, source=str(alvo))
