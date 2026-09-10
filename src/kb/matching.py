"""Casamento entre o catálogo do NOC e o que a coleta observou.

## O problema, com o caso real que o define

A primeira tentativa casou por substring. O item `STALL` do wiki (coletor do
MSMonitor parado) casou com o alerta `Linux: Number of installed packages has
been changed`, porque "in**stall**ed" contém "stall". O procedimento de plantão
telefônico do MSMonitor teria sido anexado a um alerta de inventário de pacotes.

Por isso o casamento aqui é **por palavra inteira**, e nunca é aplicado sozinho:

    \bstall\b   x  "number of installed packages"   -> não casa
    \bstall\b   x  "stall detectado no coletor"     -> casa

## Os sinais

Todos determinísticos, locais e explicáveis — cada um vira uma frase que o
operador lê antes de confirmar:

    igualdade       o nome do wiki é o nome do alerta            forte
    frase inteira   o nome do wiki aparece inteiro no alerta     forte
    cobertura       fração das palavras do wiki no alerta        proporcional
    host            o host do wiki bate com o host do alerta     reforça
    camelCase       `RotinaComFalha` -> "rotina com falha"       alternativa

Nenhum sinal isolado confirma nada. O que o módulo devolve é uma lista de
sugestões ordenadas com os motivos ao lado; quem decide é a pessoa.

## Alvo do vínculo

O vínculo é sugerido para a **família técnica** (que tem o texto do alerta) e,
por tabela, para as **regras operacionais** que contêm essa família — que é
onde a Fase 4 documenta. As duas opções são oferecidas; o operador escolhe o
nível em que aquele conhecimento vale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..keys import normalize_text

#: Palavras que não distinguem nada num nome de alerta e por isso não contam
#: para a cobertura — senão "is low" casaria com meio ambiente.
_VAZIAS = frozenset({
    "a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "no", "na",
    "por", "para", "com", "the", "of", "is", "are", "to", "in", "on", "at", "be",
    "has", "have", "been", "was", "and", "or", "um", "uma", "ao", "se", "que",
})

#: Placeholders do wiki: `[xxxxxx]`, `()`, `...`. Não são texto a casar.
_PLACEHOLDER = re.compile(r"\[x+\]|\(\s*\)|\.\.\.|…", re.IGNORECASE)

#: Fronteira de palavra de verdade: `stall` não casa dentro de `installed`.
_PALAVRA = re.compile(r"[a-z0-9]+")

#: `RotinaComFalha` -> `Rotina Com Falha`. Só é tentado quando a forma literal
#: não casou, e o motivo diz que foi por aqui.
_CAMEL = re.compile(r"(?<=[a-zà-ÿ0-9])(?=[A-ZÀ-Þ])")

HIGH, MEDIUM, LOW = "high", "medium", "low"
CONFIDENCE_LABELS = {HIGH: "Alta", MEDIUM: "Média", LOW: "Baixa"}

#: Abaixo disto o casamento é fraco demais para virar sugestão: mostrar
#: dezenas de "talvez" faz o operador parar de ler os motivos.
MIN_COVERAGE = 0.6

#: Um nome de uma palavra só (`STALL`, `RotinaComFalha`) casa por acaso com
#: facilidade. Ele entra, mas com o teto de confiança rebaixado, a menos que o
#: host do wiki também confirme.
MIN_TOKENS_FOR_HIGH = 2

#: Quanto do texto do alerta o nome do wiki precisa ocupar para o casamento ser
#: "é este alerta" em vez de "aparece dentro deste alerta". `Http Response -
#: Feedz` dentro de `Failed step of scenario "Http Response - Feedz"` é um
#: alerta **relacionado**, não o mesmo — e a confiança tem que dizer isso.
MIN_PROPORCAO_PARA_ALTA = 0.6


def palavras(texto: str) -> list[str]:
    """Palavras significativas de um texto, normalizadas."""
    return [p for p in _PALAVRA.findall(normalize_text(texto)) if p not in _VAZIAS and len(p) > 1]


def _sem_placeholder(nome: str) -> str:
    return re.sub(r"\s+", " ", _PLACEHOLDER.sub(" ", nome)).strip(" :-")


def _camel_para_frase(nome: str) -> str:
    return _CAMEL.sub(" ", nome)


def _frase_inteira(agulha: str, palheiro: str) -> bool:
    """A agulha aparece no palheiro como sequência de palavras inteiras."""
    tokens = _PALAVRA.findall(normalize_text(agulha))
    if not tokens:
        return False
    padrao = r"\b" + r"\W+".join(re.escape(t) for t in tokens) + r"\b"
    return re.search(padrao, normalize_text(palheiro)) is not None


def _cobertura(tokens: list[str], palheiro_normalizado: str) -> tuple[float, list[str]]:
    """Fração das palavras do wiki presentes no alvo, como palavras inteiras."""
    if not tokens:
        return 0.0, []
    presentes = [t for t in tokens if re.search(rf"\b{re.escape(t)}\b", palheiro_normalizado)]
    return len(presentes) / len(tokens), presentes


@dataclass
class Suggestion:
    """Um vínculo POSSÍVEL entre um item do wiki e um alvo do sistema."""

    entry_id: str
    kind: str                      # "family" | "rule"
    target_id: str
    label: str
    confidence: str
    reasons: list[str] = field(default_factory=list)
    score: float = 0.0
    alerts: int = 0
    hosts: list[str] = field(default_factory=list)
    group: str = ""
    procedure_status: str = "missing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "kind": self.kind,
            "target_id": self.target_id,
            "label": self.label,
            "confidence": self.confidence,
            "confidence_label": CONFIDENCE_LABELS[self.confidence],
            "reasons": self.reasons,
            "score": round(self.score, 3),
            "alerts": self.alerts,
            "hosts": self.hosts,
            "group": self.group,
            "procedure_status": self.procedure_status,
        }


def _avaliar(nome_wiki: str, host_wiki: str, alvo_texto: str,
             hosts_alvo: Iterable[str]) -> tuple[float, str, list[str]] | None:
    """Compara um nome do wiki com o texto de um alvo.

    Devolve `(score, confiança, motivos)` ou `None` quando o casamento é fraco
    demais para virar sugestão.
    """
    limpo = _sem_placeholder(nome_wiki)
    tokens = palavras(limpo)
    if not tokens:
        return None

    alvo_normalizado = normalize_text(alvo_texto)
    motivos: list[str] = []
    score = 0.0
    forma = ""

    if normalize_text(limpo) == alvo_normalizado:
        score = 1.0
        forma = "igual"
        motivos.append(f"o nome no wiki é exatamente o texto do alerta: “{alvo_texto}”")
    elif _frase_inteira(limpo, alvo_texto):
        score = 0.9
        forma = "frase"
        motivos.append(f"“{limpo}” aparece inteiro, como palavras completas, em “{alvo_texto}”")
    elif _frase_inteira(_camel_para_frase(limpo), alvo_texto):
        score = 0.8
        forma = "camel"
        motivos.append(
            f"“{limpo}” separado em palavras (“{_camel_para_frase(limpo).strip()}”) "
            f"aparece inteiro em “{alvo_texto}”"
        )
    else:
        cobertura, presentes = _cobertura(tokens, alvo_normalizado)
        if cobertura < MIN_COVERAGE:
            return None
        score = 0.5 + 0.3 * cobertura
        forma = "cobertura"
        motivos.append(
            f"{len(presentes)} de {len(tokens)} palavras do wiki aparecem como palavras "
            f"inteiras em “{alvo_texto}”: {', '.join(presentes)}"
        )

    # Host do wiki confirmando: é o desempate que separa "/: Disk space is
    # critically low" no Zabbix-Proxy do mesmo texto em outros três hosts.
    host_confere = False
    tokens_host = palavras(host_wiki)
    if tokens_host:
        for nome in hosts_alvo:
            alvo_host = normalize_text(nome)
            if all(re.search(rf"\b{re.escape(t)}\b", alvo_host) for t in tokens_host):
                host_confere = True
                motivos.append(f"o host do wiki (“{host_wiki}”) confere com o host “{nome}”")
                break
        if not host_confere:
            motivos.append(
                f"⚠ o host do wiki é “{host_wiki}”, que não está entre os hosts deste alvo — "
                "o texto casa, o host não"
            )
    score += 0.15 if host_confere else 0.0

    curto = len(tokens) < MIN_TOKENS_FOR_HIGH
    if curto:
        motivos.append(
            f"⚠ o nome no wiki tem uma palavra só (“{limpo}”) — casa por acaso com facilidade; "
            "confira o alerta antes de confirmar"
        )

    # Quanto do alerta o nome do wiki ocupa. Um nome que é só um pedaço de um
    # texto bem maior descreve, na melhor das hipóteses, um alerta vizinho.
    tokens_alvo = palavras(alvo_texto)
    proporcao = len(tokens) / len(tokens_alvo) if tokens_alvo else 0.0
    fragmento = forma != "igual" and proporcao < MIN_PROPORCAO_PARA_ALTA
    if fragmento:
        motivos.append(
            f"⚠ o nome do wiki cobre {len(tokens)} das {len(tokens_alvo)} palavras do alerta — "
            "pode ser um alerta relacionado, e não o mesmo"
        )

    if forma == "igual" and host_confere:
        confianca = HIGH
    elif forma in ("igual", "frase") and not curto and not fragmento:
        confianca = HIGH if score >= 0.9 else MEDIUM
    elif forma in ("frase", "camel"):
        confianca = MEDIUM
    else:
        confianca = MEDIUM if score >= 0.75 and host_confere else LOW

    if curto and confianca == HIGH and not host_confere:
        confianca = MEDIUM
    return score, confianca, motivos


def suggest_for_entry(entry: Any, modelo: Any, *, limite: int = 8) -> list[Suggestion]:
    """Sugestões de vínculo de um item do wiki, das mais fortes para as fracas."""
    sugestoes: list[Suggestion] = []

    for familia in modelo.families.values():
        avaliacao = _avaliar(entry.name, entry.host, familia.label, familia.hosts.values())
        if avaliacao is None:
            continue
        score, confianca, motivos = avaliacao
        procedimento = modelo.procedure_of_family(familia.id)
        sugestoes.append(Suggestion(
            entry_id=entry.id, kind="family", target_id=familia.id, label=familia.label,
            confidence=confianca, reasons=motivos, score=score,
            alerts=len(familia.alert_ids), hosts=sorted(familia.hosts.values())[:6],
            group=", ".join(sorted(familia.host_groups)[:2]),
            procedure_status=procedimento["status"],
        ))

    sugestoes.sort(key=lambda s: (-s.score, -s.alerts, s.label))
    sugestoes = sugestoes[:limite]

    # As regras que contêm as famílias sugeridas. A Fase 4 documenta neste
    # nível, então o operador precisa ver a opção — mas ela é derivada, e o
    # motivo diz isso em vez de fingir que a regra casou por texto.
    vistas: set[str] = set()
    derivadas: list[Suggestion] = []
    for sugestao in sugestoes:
        familia = modelo.families.get(sugestao.target_id)
        if familia is None:
            continue
        for alerta_id in familia.alert_ids:
            for regra_id in modelo.rules_of_alert.get(alerta_id, []):
                if regra_id in vistas:
                    continue
                regra = modelo.rules.get(regra_id)
                if regra is None:
                    continue
                vistas.add(regra_id)
                derivadas.append(Suggestion(
                    entry_id=entry.id, kind="rule", target_id=regra_id,
                    label=f"{regra.label} — {regra.group_name}",
                    confidence=MEDIUM if sugestao.confidence == HIGH else LOW,
                    reasons=[
                        f"a família “{familia.label}”, que casou com este item do wiki, "
                        f"faz parte deste agrupamento operacional",
                        *sugestao.reasons,
                    ],
                    score=sugestao.score - 0.05,
                    alerts=len(regra.alert_ids), hosts=sorted(regra.hosts.values())[:6],
                    group=regra.group_name,
                    procedure_status=modelo.procedure_of_rule(regra_id)["status"],
                ))
    derivadas.sort(key=lambda s: (-s.score, -s.alerts, s.label))
    return sugestoes + derivadas[:limite]
