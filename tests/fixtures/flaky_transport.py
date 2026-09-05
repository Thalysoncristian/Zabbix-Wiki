"""Transportes que simulam um Zabbix sob estresse.

Servem para testar exatamente o que quebrou no ambiente real: o servidor
devolve HTTP 500 quando a consulta é grande demais, e responde normalmente
quando ela é pequena.
"""

from __future__ import annotations

from typing import Any, Callable

from src.zabbix_client import ZabbixTransientError


class FailNTimes:
    """Falha as N primeiras chamadas de um método e depois funciona.

    Testa o retry puro: a mesma consulta, repetida, acaba passando.
    """

    def __init__(self, inner: Callable[..., dict[str, Any]], *, failures: int, method: str = "", status: int = 500):
        self.inner = inner
        self.remaining = failures
        self.method = method
        self.status = status
        self.attempts = 0

    def __call__(self, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        alvo = not self.method or payload.get("method") == self.method
        if alvo:
            self.attempts += 1
            if self.remaining > 0:
                self.remaining -= 1
                raise ZabbixTransientError(f"HTTP {self.status}: servidor ocupado", status=self.status)
        return self.inner(payload, headers)


class RejectLargeBatches:
    """Recusa qualquer chamada cujo lote de IDs seja maior que `max_ids`.

    É o comportamento observado no Zabbix real: `trigger.get` com uma lista
    grande estoura tempo/memória e devolve HTTP 500 de corpo vazio; a mesma
    consulta com metade dos IDs responde na hora.
    """

    def __init__(self, inner: Callable[..., dict[str, Any]], *, max_ids: int, id_fields: tuple[str, ...] = ()):
        self.inner = inner
        self.max_ids = max_ids
        self.id_fields = id_fields or ("triggerids", "hostids", "itemids", "groupids", "templateids")
        #: Tamanhos de lote recusados, na ordem — é o que o teste inspeciona.
        self.rejected_sizes: list[int] = []
        self.accepted_sizes: list[int] = []

    def __call__(self, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        params = payload.get("params") or {}
        for campo in self.id_fields:
            valores = params.get(campo)
            if isinstance(valores, list) and len(valores) > self.max_ids:
                self.rejected_sizes.append(len(valores))
                raise ZabbixTransientError(
                    f"HTTP 500 em /api_jsonrpc.php: (corpo vazio) — lote de {len(valores)} recusado",
                    status=500,
                )
            if isinstance(valores, list):
                self.accepted_sizes.append(len(valores))
        return self.inner(payload, headers)
