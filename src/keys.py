"""Chave lógica do alerta (`alert_key`) e hash técnico (`source_hash`).

Princípios:

* `triggerid` é referência técnica, **não** identidade de negócio. Se o trigger
  for recriado no Zabbix, o `triggerid` muda e a documentação operacional não
  pode ser perdida.
* A identidade é derivada de informações mais estáveis:
  escopo (template de origem, quando o trigger é herdado; senão o host) +
  descrição normalizada do trigger.
* `source_hash` cobre apenas o FATO TÉCNICO vindo do Zabbix, para detectar
  "o Zabbix mudou o alerta" sem confundir com "um humano editou a ficha".
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

#: Campos técnicos que compõem o source_hash (documentado no README).
SOURCE_HASH_FIELDS = (
    "description_raw",
    "expression_signature",
    "recovery_mode",
    "recovery_expression_signature",
    "priority",
    "opdata",
    "event_name",
    "comments",
    "manual_close",
    "tags",
    "items",
    "host",
    "host_groups",
    "templates",
    "source_template",
)

_MACRO_RE = re.compile(r"\{[^{}]{0,120}\}")
_NON_SLUG_RE = re.compile(r"[^a-z0-9]+")


def strip_accents(text: str) -> str:
    """Remove acentuação preservando as letras base (NFKD)."""
    normalized = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Minúsculas, sem acentos, espaços colapsados. Determinístico."""
    return re.sub(r"\s+", " ", strip_accents(str(text or "")).lower()).strip()


def slugify(text: str, *, fallback: str = "") -> str:
    """Gera um slug estável: minúsculo, sem acentos, separado por hífen."""
    slug = _NON_SLUG_RE.sub("-", normalize_text(text)).strip("-")
    return slug or fallback


def normalize_description(description: str) -> str:
    """Normaliza a descrição do trigger para uso na chave.

    Macros (`{HOST.NAME}`, `{ITEM.VALUE}`, `{$LIMITE}`) são substituídas por um
    marcador único, para que a chave não dependa do valor expandido — que muda
    por host e por coleta.
    """
    without_macros = _MACRO_RE.sub(" macro ", str(description or ""))
    return slugify(without_macros)


def short_hash(text: str, length: int = 8) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:length]


def build_alert_key(scope_name: str, description: str, *, triggerid: str = "") -> str:
    """`<escopo>|<descricao>` — ex.: `template-linux-disk|disk-space-critically-low`."""
    scope_slug = slugify(scope_name, fallback="sem-escopo")
    desc_slug = normalize_description(description)
    if not desc_slug:
        # Descrição composta apenas de macros/símbolos: mantém determinismo.
        desc_slug = f"trigger-{short_hash(description or triggerid)}"
    return f"{scope_slug}|{desc_slug}"


def expression_signature(expression: str, host_aliases: tuple[str, ...] = ()) -> str:
    """Assinatura estável de uma expressão de trigger.

    A expressão expandida contém o nome do host (`last(/HOST/chave)`), o que a
    torna diferente para cada host que usa o mesmo trigger de template. Aqui os
    nomes de host conhecidos são substituídos por `{HOST}` e macros por
    `{MACRO}`, de forma que dois triggers do mesmo template gerem a mesma
    assinatura — e dois triggers realmente diferentes gerem assinaturas
    diferentes.
    """
    text = _MACRO_RE.sub("{MACRO}", str(expression or ""))
    for alias in sorted({a for a in host_aliases if a}, key=len, reverse=True):
        text = text.replace(f"/{alias}/", "/{HOST}/")
    return re.sub(r"\s+", "", text)


def canonical_json(payload: Any) -> str:
    """Serialização determinística usada no cálculo dos hashes."""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def compute_source_hash(technical: dict[str, Any]) -> str:
    """SHA-256 sobre os campos técnicos relevantes (ordem determinística).

    NÃO entram no hash:
      * `triggerid` (identidade técnica volátil);
      * `value` (estado runtime: OK/PROBLEM muda a toda hora);
      * `status` (habilitado/desabilitado não muda o procedimento operacional);
      * qualquer conteúdo humano (`operational`) — que ainda não existe nesta etapa.
    """
    material = {field: technical.get(field) for field in SOURCE_HASH_FIELDS}
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
