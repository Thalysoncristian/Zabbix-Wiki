"""Redação de segredos antes de persistir ou exibir dados do Zabbix.

## Por que isto existe

A primeira coleta real do ambiente inteiro trouxe uma expressão assim:

    avg(/Saq - AWS/aws_check.py[--access-key, "AKIA................",
        --secret-key, "................................"], 5m) >= 5

Ou seja: uma credencial de produção, em texto claro, dentro da configuração do
Zabbix. Quem tem leitura na API a enxerga — e, a partir da Fase 2, ela também
ia parar em `zabbix_raw.json`, em `alerts.json` e (na Fase 3) numa página web.
O Zabbix-Wiki não criou o problema, mas não pode multiplicá-lo.

## O que a redação faz — e o que ela não faz

Ela substitui **o valor** do segredo, nunca o nome do parâmetro:

    --secret-key, "KwoaLm..."   ->   --secret-key, "[REDACTED:3f7a1c9e]"

O sufixo é um hash curto do valor original. Isso é deliberado e importante:

* dois segredos **diferentes** continuam produzindo textos diferentes, então
  dois triggers que só diferem na credencial continuam tendo assinaturas de
  expressão distintas — a detecção de colisão da Fase 1 segue funcionando;
* o **mesmo** segredo produz sempre o mesmo marcador, então `source_hash` é
  estável entre coletas: a ficha não cai em `review_needed` a cada execução;
* o hash não permite recuperar o segredo.

A redação acontece **antes** da normalização, então `source_hash` e
`expression_signature` já nascem calculados sobre o texto redigido. É uma
mudança de uma vez só: fichas criadas antes desta versão vão acusar
`review_needed` na primeira reconciliação, e depois estabilizam.

## O que NÃO é redigido

Macros do Zabbix (`{$PASSWORD}`, `{$API.TOKEN}`) são *referências* a um valor
guardado no Zabbix, não o valor. Redigi-las destruiria informação operacional
útil sem esconder segredo nenhum.

Texto sem valor também fica: uma descrição "Certificate password expires in 30
days" não tem segredo — tem a palavra "password". A redação só age quando há um
separador e um valor logo depois.
"""

from __future__ import annotations

import re
from typing import Any

from .keys import short_hash

#: Nomes de parâmetro que indicam segredo quando seguidos de um valor.
#:
#: `\w*secret` em vez de `secret` porque o lookbehind `(?<![\w.-])` impede
#: casar no meio de uma palavra: com `secret` puro, `--hmacsecret,<valor>`
#: passava batido, e passou mesmo — apareceu em texto claro num trigger de
#: PIX do ambiente real. Qualquer parâmetro terminado em "secret" é segredo.
_NOME_SENSIVEL = (
    r"access[-_]?key(?:[-_]?id)?"
    r"|secret[-_]?(?:access[-_]?)?key"
    r"|\w*secret"
    r"|passwd|password|pwd"
    r"|api[-_]?key|apikey"
    r"|auth[-_]?token|access[-_]?token|token"
    r"|authorization"
    r"|credentials?"
    r"|private[-_]?key"
    # A METADE IDENTIFICADORA do par também é credencial. `--clientid,
    # servico@empresa.com` ao lado de `--clientsecret` é a conta de serviço em
    # texto claro: quem a lê já tem metade do que precisa, e ela vaza o nome
    # real da conta mesmo depois de o segredo virar [REDACTED].
    #
    # `user` sozinho fica DE FORA de propósito. Ele aparece em item legítimo
    # ("processos do usuário X", "sessões por usuário") e redigir isso
    # destruiria dado operacional para proteger o que não é segredo.
    r"|client[-_]?id"
    r"|user[-_]?name|username"
    r"|login"
)

#: `--secret-key, "valor"` / `password="valor"` / `token: 'valor'`
#: O valor entre aspas é o caso mais comum em chaves de item do Zabbix.
_PAR_COM_ASPAS = re.compile(
    rf"(?P<nome>(?<![\w.\-/])(?:--)?(?:{_NOME_SENSIVEL})\s*[:=,]\s*)(?P<aspa>[\"'])(?P<valor>[^\"']{{4,}})(?P=aspa)",
    re.IGNORECASE,
)

#: `password=valor` / `token: valor` / `--clientsecret,valor` sem aspas. O
#: valor termina no primeiro separador — vírgula, espaço, `]`, `)` ou fim.
#:
#: A vírgula precisa estar entre os separadores de NOME (`[:=,]`), e não só
#: entre os terminadores de valor: chave de item do Zabbix separa parâmetro
#: por vírgula, então `--clientsecret,<valor>` é a forma mais comum de o
#: segredo aparecer ali. Sem ela, o par com aspas era redigido e o sem aspas
#: — o mesmo segredo, escrito de outro jeito — passava direto.
_PAR_SEM_ASPAS = re.compile(
    rf"(?P<nome>(?<![\w.\-/])(?:--)?(?:{_NOME_SENSIVEL})\s*[:=,]\s*)(?P<valor>[^\s,;\]\)\"'&]{{8,}})",
    re.IGNORECASE,
)

#: `Authorization: Bearer <token>`
_BEARER = re.compile(r"(?P<nome>Bearer\s+)(?P<valor>[A-Za-z0-9\-._~+/]{16,}=*)", re.IGNORECASE)

#: IDs de chave de acesso da AWS, que são reconhecíveis sozinhos.
_AWS_KEY_ID = re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA|ANVA|AIPA)[0-9A-Z]{16}\b")

#: Macro do Zabbix: referência a um valor, não o valor. Nunca é redigida.
_MACRO = re.compile(r"^\{[$#]?[^{}]*\}$")

#: Marcador já aplicado. Redigir de novo mudaria o hash — e como o
#: `source_hash` é calculado sobre o texto redigido, uma segunda passada (num
#: merge de snapshots já redigidos, por exemplo) jogaria toda a documentação
#: em `review_needed` sem nenhum motivo real.
#:
#: O teste é por PREFIXO, e não pelo marcador inteiro. `]` está fora da classe
#: de caracteres do valor em `_PAR_SEM_ASPAS`, então dentro de uma chave de
#: item o grupo capturado é `[REDACTED:4bdf095e` — sem o fecha-colchetes. Uma
#: âncora `$` não casava com isso, a guarda não disparava, e a segunda passada
#: redigia o próprio marcador: hash novo e um `]` órfão no texto.
_JA_REDIGIDO = re.compile(r"^\[REDACTED:")

#: Campos de texto onde um segredo pode aparecer. `description_raw` entra
#: porque nada impede alguém de escrever a senha no nome do trigger.
#:
#: A lista cobre os DOIS formatos de propósito: os nomes do snapshot bruto
#: (`expression`, vindos da API do Zabbix) e os nomes que a normalização
#: deriva deles (`expression_expanded`, `expression_signature`…). No fluxo
#: normal só os primeiros importam, porque a redação roda antes de normalizar
#: — mas sem os segundos a função fica inútil justamente quando mais se
#: precisa dela: para limpar dados JÁ normalizados, coletados por uma versão
#: do coletor anterior à redação. Foi o que aconteceu com o snapshot
#: 20260905_181510, coletado 36 minutos antes de este módulo existir.
CAMPOS_DE_TEXTO = (
    # snapshot bruto (API do Zabbix)
    "expression",
    "recovery_expression",
    "description",
    "comments",
    "opdata",
    "event_name",
    "key_",
    "name",
    "name_resolved",
    "url",
    "value",
    # alerta normalizado (derivados dos acima)
    "expression_raw",
    "expression_expanded",
    "expression_signature",
    "recovery_expression_raw",
    "recovery_expression_expanded",
    "recovery_expression_signature",
    "description_raw",
    "description_normalized",
    "prototype_description",
    "alert_key_basis_description",
)


def _marcador(valor: str) -> str:
    return f"[REDACTED:{short_hash(valor)}]"


def _substituir(match: re.Match[str], grupo: str = "valor") -> str:
    valor = match.group(grupo)
    limpo = valor.strip()
    if _MACRO.match(limpo):
        # `{$SENHA}` é uma referência do Zabbix, não o segredo em si.
        return match.group(0)
    if _JA_REDIGIDO.match(limpo):
        # Redigir o marcador seria redigir o hash: a operação precisa ser
        # idempotente para o source_hash ser estável entre coletas.
        return match.group(0)
    prefixo = match.group(0)[: match.start(grupo) - match.start(0)]
    sufixo = match.group(0)[match.end(grupo) - match.start(0):]
    return f"{prefixo}{_marcador(valor)}{sufixo}"


def redact_text(texto: Any) -> tuple[Any, int]:
    """Redige segredos num texto. Devolve `(texto, quantidade_redigida)`."""
    if not isinstance(texto, str) or not texto:
        return texto, 0

    total = 0

    def conta(match: re.Match[str]) -> str:
        nonlocal total
        substituido = _substituir(match)
        if substituido != match.group(0):
            total += 1
        return substituido

    resultado = _PAR_COM_ASPAS.sub(conta, texto)
    resultado = _PAR_SEM_ASPAS.sub(conta, resultado)
    resultado = _BEARER.sub(conta, resultado)

    def conta_aws(match: re.Match[str]) -> str:
        nonlocal total
        # Um ID de chave já redigido pelo passo anterior não é contado de novo.
        total += 1
        return _marcador(match.group(0))

    resultado = _AWS_KEY_ID.sub(conta_aws, resultado)
    return resultado, total


def redact_value(valor: Any) -> tuple[Any, int]:
    """Redige recursivamente strings dentro de dicts, listas e escalares."""
    if isinstance(valor, str):
        return redact_text(valor)
    if isinstance(valor, dict):
        total = 0
        saida: dict[Any, Any] = {}
        for chave, item in valor.items():
            # Só campos de texto conhecidos são varridos: varrer tudo faria a
            # redação passar por IDs e enums sem ganho nenhum.
            if isinstance(item, str) and chave not in CAMPOS_DE_TEXTO:
                saida[chave] = item
                continue
            saida[chave], n = redact_value(item)
            total += n
        return saida, total
    if isinstance(valor, list):
        total = 0
        saida_lista = []
        for item in valor:
            redigido, n = redact_value(item)
            saida_lista.append(redigido)
            total += n
        return saida_lista, total
    return valor, 0


def redact_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Redige uma coleção do snapshot bruto."""
    saida: list[dict[str, Any]] = []
    total = 0
    for row in rows:
        redigido, n = redact_value(row)
        saida.append(redigido)
        total += n
    return saida, total


def redact_snapshot_data(
    data: dict[str, list[dict[str, Any]]]
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Redige todas as coleções de um snapshot bruto.

    Devolve os dados redigidos e um relatório para os metadados — a redação
    precisa ser auditável: quem lê o snapshot tem direito de saber que ele foi
    alterado, quantos valores foram tocados e em quais coleções.
    """
    saida: dict[str, list[dict[str, Any]]] = {}
    por_colecao: dict[str, int] = {}
    total = 0

    for nome, rows in data.items():
        redigidas, n = redact_rows(rows)
        saida[nome] = redigidas
        if n:
            por_colecao[nome] = n
            total += n

    relatorio = {
        "enabled": True,
        "values_redacted": total,
        "by_collection": por_colecao,
        "note": (
            "Valores de segredo encontrados na configuração do Zabbix foram "
            "substituídos por [REDACTED:<hash>]. O nome do parâmetro e a "
            "estrutura da expressão foram preservados."
        ),
    }
    return saida, relatorio


def contains_secret(texto: str) -> bool:
    """Heurística usada por testes e pelo `check`: sobrou segredo aqui?"""
    _, total = redact_text(texto)
    return total > 0
