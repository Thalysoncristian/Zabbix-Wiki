"""Modelo da ficha operacional.

Cada ficha é um arquivo JSON em `docs/alerts/` com três áreas de
responsabilidade **separadas de propósito**:

    zabbix         FATO TÉCNICO   — vem da coleta, ninguém edita à mão
    ai_suggestion  SUGESTÃO       — a IA propõe, nunca decide
    operational    VERDADE HUMANA — o procedimento oficial

A IA nunca escreve em `operational`. Uma sugestão pode ser copiada para a
ficha por uma pessoa, mas a aprovação continua humana.

Nível da ficha (`doc_level`) — decisão que veio dos dados reais da ETAPA 1:

    family     regra genérica  ("qualquer serviço do Windows parado")
    override   exceção humana   ("neste host o procedimento é outro")

Numa coleta real, 1.229 de 1.380 alertas vinham de LLD: um alerta por serviço,
por ponto de montagem, por chamado. O procedimento é o mesmo para a família
toda, então a coleta **sempre** gera ficha de família. O override existe só
quando uma pessoa decide que um caso específico foge da regra. O lookup
resolve override primeiro, família depois.

O nível nunca é inferido por contagem de instâncias. Se fosse, descobrir um
ponto de montagem novo mudaria a chave da ficha e a documentação já escrita
ficaria órfã — um alerta às 3h da manhã cairia numa ficha vazia.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..keys import canonical_json, short_hash, slugify
from .status import ALL_STATUSES, DOCUMENTED_STATUSES, UNDOCUMENTED

SCHEMA_VERSION = 1

SCOPE_ZABBIX = "zabbix"
SCOPE_MANUAL = "manual"

#: Toda ficha gerada pela coleta é de FAMÍLIA. O nível nunca é decidido por
#: contagem de instâncias: se dependesse disso, descobrir um ponto de montagem
#: novo mudaria a chave da ficha e abandonaria a documentação já escrita.
LEVEL_FAMILY = "family"
#: Override criado por uma pessoa: "para ESTE host o procedimento é outro".
LEVEL_OVERRIDE = "override"

#: Caracteres proibidos em nome de arquivo no Windows (e problemáticos no resto).
_UNSAFE_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
#: Nomes reservados pelo Windows, independentemente da extensão.
_RESERVED_WINDOWS = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
)
#: Margem confortável abaixo do limite de caminho do Windows (260).
MAX_FILENAME_STEM = 110


def utc_now() -> str:
    """Instante atual em UTC, com precisão de segundo (para leitura humana)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_precise() -> str:
    """Instante atual em UTC com microssegundos.

    `last_modified_at` precisa distinguir duas gravações no mesmo segundo —
    é justamente o cenário de duas pessoas editando a mesma ficha às 03h.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def alert_key_to_filename(alert_key: str) -> str:
    """Converte a `alert_key` em um nome de arquivo seguro e determinístico.

    A `alert_key` usa `|` como separador — inválido em nome de arquivo no
    Windows — e pode ficar muito longa (descrições de LLD chegam a passar de
    100 caracteres). O nome é sanitizado e, quando truncado, recebe um sufixo
    de hash da chave completa para continuar único e reversível pelo índice.
    A chave verdadeira permanece dentro do JSON: o arquivo é só o endereço.
    """
    stem = _UNSAFE_FILENAME.sub("_", alert_key.strip().replace("|", "__"))
    stem = re.sub(r"\s+", "-", stem).strip("._-") or "alerta"

    if stem.split(".")[0].lower() in _RESERVED_WINDOWS:
        stem = f"_{stem}"

    if len(stem) > MAX_FILENAME_STEM:
        stem = f"{stem[:MAX_FILENAME_STEM].rstrip('._-')}~{short_hash(alert_key)}"

    return f"{stem}.json"


def build_family_key(alert: dict[str, Any]) -> str:
    """Chave da família à qual o alerta pertence.

    LLD: a regra de descoberta mais a descrição crua do protótipo — o que é
    comum a todas as entidades descobertas. Trigger direto: a descrição
    normalizada mais a assinatura da expressão, que atravessa hosts.

    A chave não depende de quantas instâncias existem hoje. Um protótipo de LLD
    é uma família mesmo quando só uma entidade foi descoberta até agora.
    """
    zbx = alert.get("zabbix") or {}
    escopo = (alert.get("alert_key_scope") or {}).get("name", "")

    if zbx.get("discovered") and zbx.get("prototype_description"):
        regra = (zbx.get("discovery_rule") or {}).get("key_") or (zbx.get("discovery_rule") or {}).get("name") or ""
        return "|".join(["lld", slugify(escopo, fallback="sem-escopo"), slugify(regra, fallback="sem-regra"),
                         slugify(zbx["prototype_description"], fallback="sem-descricao")])

    return "|".join(["rule", slugify(zbx.get("description_normalized", ""), fallback="sem-descricao"),
                     short_hash(zbx.get("expression_signature", ""))])


#: Campos do PROCEDIMENTO operacional (item 15 da Fase 2).
#:
#: O procedimento não é um modelo novo ao lado da ficha: ele É o bloco
#: `operational`, que já era a camada de verdade humana. Criar uma entidade
#: `Procedure` paralela duplicaria a máquina de estados, o hash de revisão e o
#: controle de concorrência — e abriria a porta para as duas divergirem.
#:
#: A regra dura continua valendo: nenhum destes campos é preenchido pela
#: coleta ou pela IA. Enquanto ninguém escrever, `doc_status` é
#: `undocumented` — que é exatamente o `procedure_status = missing` pedido.
PROCEDURE_FIELDS: tuple[str, ...] = (
    "title",
    "objective",
    "symptoms",
    "probable_cause",
    "checks_before_action",
    "actions",
    "validation",
    "risks",
    "notes",
)


def empty_operational() -> dict[str, Any]:
    """Bloco operacional vazio — a ficha nasce assim, esperando um humano."""
    return {
        "doc_status": UNDOCUMENTED,
        # --- procedimento (preenchido só por pessoas) ---------------------
        "title": "",
        "objective": "",
        "symptoms": [],
        "actions": [],
        "validation": "",
        "risks": [],
        # --- campos originais da ETAPA 2 ----------------------------------
        "meaning": "",
        "probable_cause": "",
        "self_resolves": None,
        "wait_before_ticket_minutes": None,
        "checks_before_action": [],
        "requires_ticket": None,
        "routing": {
            "team": "",
            "ticket_category": "",
            "ticket_subcategory": "",
            "ticket_queue": "",
            "channel": "",
        },
        "schedule_policy": {"type": "ref", "name": "default_business_hours"},
        "evidence_required": [],
        "escalation": {"after_minutes": None, "to": "", "channel": ""},
        "resolution_criteria": "",
        "notes": "",
        "imported_from": None,
        "reviewed_by": "",
        "reviewed_at": None,
        "last_zabbix_hash_at_review": None,
    }


@dataclass
class AlertDoc:
    """Ficha operacional de um alerta."""

    alert_key: str
    scope: str = SCOPE_ZABBIX
    doc_level: str = LEVEL_FAMILY
    family_key: str | None = None
    zabbix: dict[str, Any] | None = None
    ai_suggestion: dict[str, Any] | None = None
    operational: dict[str, Any] = field(default_factory=empty_operational)
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    last_modified_at: str = field(default_factory=utc_now_precise)
    #: Token de concorrência: incrementa a cada alteração. Mais confiável que
    #: comparar timestamps, que podem empatar dentro do mesmo instante.
    revision: int = 0
    # Presença no Zabbix: a ficha sobrevive ao alerta sumir da coleta.
    present_in_zabbix: bool = True
    last_seen_at: str | None = None
    instances: list[dict[str, Any]] = field(default_factory=list)

    # ------------------------------------------------------------------ estado
    @property
    def doc_status(self) -> str:
        return self.operational.get("doc_status", UNDOCUMENTED)

    @property
    def procedure_status(self) -> str:
        """Estado do PROCEDIMENTO, derivado do `doc_status`.

        `missing` enquanto ninguém escreveu nada. Não existe estado "sugerido
        pela IA": uma sugestão vive em `ai_suggestion` e nunca conta como
        procedimento — só vira procedimento quando uma pessoa a escreve aqui.
        """
        if self.doc_status in DOCUMENTED_STATUSES:
            return "documented"
        if self.doc_status == "review_needed":
            return "needs_review"
        if self.doc_status == "not_applicable":
            return "not_applicable"
        if self.doc_status == "pending_review":
            return "draft"
        return "missing"

    @property
    def filename(self) -> str:
        return alert_key_to_filename(self.alert_key)

    @property
    def source_hash(self) -> str | None:
        """Hash técnico usado para detectar mudança no Zabbix.

        Numa ficha de família é o hash da família — trocar instâncias (um
        chamado fecha, um serviço é descoberto) não pode pedir revisão.
        """
        zbx = self.zabbix or {}
        if self.doc_level == LEVEL_FAMILY:
            return zbx.get("family_source_hash") or zbx.get("source_hash")
        return zbx.get("source_hash")

    # ------------------------------------------------------------ serialização
    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "alert_key": self.alert_key,
            "scope": self.scope,
            "doc_level": self.doc_level,
            "family_key": self.family_key,
            "present_in_zabbix": self.present_in_zabbix,
            "created_at": self.created_at,
            "last_modified_at": self.last_modified_at,
            "revision": self.revision,
            "last_seen_at": self.last_seen_at,
            # Derivado de `operational.doc_status`, gravado para quem lê o JSON
            # de fora sem conhecer a máquina de estados.
            "procedure_status": self.procedure_status,
            "instances": self.instances,
            "zabbix": self.zabbix,
            "ai_suggestion": self.ai_suggestion,
            "operational": self.operational,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "AlertDoc":
        operational = {**empty_operational(), **(payload.get("operational") or {})}
        if operational.get("doc_status") not in ALL_STATUSES:
            operational["doc_status"] = UNDOCUMENTED
        return cls(
            alert_key=str(payload.get("alert_key") or ""),
            scope=str(payload.get("scope") or SCOPE_ZABBIX),
            doc_level=str(payload.get("doc_level") or LEVEL_FAMILY),
            family_key=payload.get("family_key"),
            zabbix=payload.get("zabbix"),
            ai_suggestion=payload.get("ai_suggestion"),
            operational=operational,
            schema_version=int(payload.get("schema_version") or SCHEMA_VERSION),
            created_at=str(payload.get("created_at") or utc_now()),
            last_modified_at=str(payload.get("last_modified_at") or utc_now_precise()),
            revision=int(payload.get("revision") or 0),
            present_in_zabbix=bool(payload.get("present_in_zabbix", True)),
            last_seen_at=payload.get("last_seen_at"),
            instances=list(payload.get("instances") or []),
        )

    @classmethod
    def from_collected_alert(cls, alert: dict[str, Any], *, doc_level: str = LEVEL_FAMILY) -> "AlertDoc":
        """Cria uma ficha nova (undocumented) a partir de um alerta coletado."""
        zbx = alert.get("zabbix") or {}
        agora = utc_now()
        return cls(
            alert_key=alert["alert_key"],
            scope=SCOPE_ZABBIX,
            doc_level=doc_level,
            family_key=build_family_key(alert),
            zabbix=zbx,
            created_at=agora,
            last_modified_at=agora,
            last_seen_at=zbx.get("collected_at") or agora,
            present_in_zabbix=True,
        )

    @classmethod
    def override(cls, alert_key: str, family_key: str) -> "AlertDoc":
        """Override de instância: procedimento específico para um alerta.

        Criado sempre por uma pessoa, nunca pela coleta. O lookup resolve o
        override primeiro e cai na família quando ele não existe.
        """
        return cls(alert_key=f"override|{alert_key}", doc_level=LEVEL_OVERRIDE, family_key=family_key)

    @classmethod
    def manual(cls, alert_key: str) -> "AlertDoc":
        """Ficha manual: documentar um alerta que ainda não existe no Zabbix."""
        return cls(alert_key=alert_key, scope=SCOPE_MANUAL, zabbix=None, present_in_zabbix=False)

    def touch(self) -> None:
        """Marca a ficha como alterada — avança o token de concorrência."""
        self.last_modified_at = utc_now_precise()
        self.revision += 1


def compute_family_hash(alerts: list[dict[str, Any]]) -> str:
    """Hash técnico de uma **família**, estável frente à troca de instâncias.

    O hash de instância (`source_hash`) cobre a descrição expandida, a expressão
    e os itens — tudo que varia entre membros da família. Usá-lo numa ficha de
    família faria a ficha inteira cair em `review_needed` toda vez que um
    chamado fechasse ou um serviço fosse descoberto, o que não é mudança de
    procedimento nenhuma.

    Aqui entram apenas os campos comuns à família: o que define a regra, não a
    entidade descoberta.
    """
    representante = min(alerts, key=lambda a: (len(a["zabbix"].get("description_raw", "")), a["alert_key"]))
    zbx = representante["zabbix"]
    escopo = (representante.get("alert_key_scope") or {}).get("name", "")

    material: dict[str, Any] = {
        "scope": escopo,
        "priority": (zbx.get("priority") or {}).get("value"),
        "recovery_mode": (zbx.get("recovery_mode") or {}).get("value"),
        "manual_close": zbx.get("manual_close"),
        "tags": sorted(f"{t.get('tag')}={t.get('value')}" for t in zbx.get("tags") or []),
        "host_groups": sorted(zbx.get("host_groups") or []),
        "templates": sorted(zbx.get("templates") or []),
    }

    if zbx.get("discovered") and zbx.get("prototype_description"):
        # A descrição do protótipo e a regra de descoberta definem a família.
        material["prototype_description"] = zbx["prototype_description"]
        material["discovery_rule"] = (zbx.get("discovery_rule") or {}).get("key_", "")
    else:
        # Trigger direto replicado em vários hosts: descrição e assinatura já
        # são neutras em relação ao host.
        material["description_normalized"] = zbx.get("description_normalized", "")
        material["expression_signature"] = zbx.get("expression_signature", "")
        material["items"] = sorted(i.get("key_", "") for i in zbx.get("items") or [])

    return f"sha256:{hashlib.sha256(canonical_json(material).encode('utf-8')).hexdigest()}"
