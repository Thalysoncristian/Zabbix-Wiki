"""Escalabilidade da coleta (Fase 2).

Cada teste aqui corresponde a um item do critério de conclusão da Fase 2:
paginação, retry, redução de lote, coleta multi-grupo e coleta parcial.
"""

from __future__ import annotations

import unittest
from typing import Any

from src.collect import SCOPE_ENVIRONMENT, SCOPE_HOST_GROUPS, SCOPE_SAMPLE, collect_raw
from src.zabbix_client import (
    TRANSIENT_STATUS,
    ZabbixError,
    ZabbixReadOnlyClient,
    ZabbixTransientError,
    chunked,
)
from tests.fixtures.fake_zabbix import FakeZabbix
from tests.fixtures.flaky_transport import FailNTimes, RejectLargeBatches


def _cliente(transport: Any, **kwargs: Any) -> ZabbixReadOnlyClient:
    kwargs.setdefault("sleep", lambda _s: None)  # testes nunca dormem de verdade
    return ZabbixReadOnlyClient("https://zabbix.local", api_token="fake-token", transport=transport, **kwargs)


class TestPaginacao(unittest.TestCase):
    """1.000 objetos com page_size=250 => 4 páginas."""

    def test_mil_objetos_em_paginas_de_250(self):
        ids = [str(i) for i in range(1, 1001)]
        chamadas: list[int] = []

        def transporte(payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
            lote = (payload.get("params") or {}).get("triggerids") or []
            chamadas.append(len(lote))
            return {"result": [{"triggerid": i} for i in lote]}

        cliente = _cliente(transporte, page_size=250)
        linhas = cliente.get_by_ids("trigger.get", "triggerids", ids, {"output": ["triggerid"]})

        self.assertEqual(len(chamadas), 4, "1000 objetos / 250 por página = 4 páginas")
        self.assertEqual(chamadas, [250, 250, 250, 250])
        self.assertEqual(len(linhas), 1000)

    def test_ultima_pagina_pode_ser_menor(self):
        ids = [str(i) for i in range(1, 1002)]  # 1001 objetos
        tamanhos = [len(lote) for lote in chunked(ids, 250)]
        self.assertEqual(tamanhos, [250, 250, 250, 250, 1])

    def test_page_size_do_argumento_vence_o_do_cliente(self):
        chamadas: list[int] = []

        def transporte(payload, headers):
            chamadas.append(len((payload.get("params") or {}).get("triggerids") or []))
            return {"result": []}

        cliente = _cliente(transporte, page_size=500)
        cliente.get_by_ids("trigger.get", "triggerids", [str(i) for i in range(1, 301)], {}, page_size=100)
        self.assertEqual(chamadas, [100, 100, 100])

    def test_progresso_informa_total_real_e_nunca_estima(self):
        eventos: list[dict[str, Any]] = []

        def transporte(payload, headers):
            lote = (payload.get("params") or {}).get("triggerids") or []
            return {"result": [{"triggerid": i} for i in lote]}

        cliente = _cliente(transporte, page_size=2)
        cliente.get_by_ids("trigger.get", "triggerids", ["1", "2", "3"], {}, on_page=eventos.append)

        paginas = [e for e in eventos if e["event"] == "page"]
        self.assertEqual([e["total"] for e in paginas], [3, 3], "o total vem da lista de IDs, não de estimativa")
        self.assertEqual([e["collected"] for e in paginas], [2, 3])


class TestRetry(unittest.TestCase):
    """HTTP 500 -> retry -> sucesso."""

    def test_http_500_e_repetido_ate_dar_certo(self):
        fake = FakeZabbix()
        transporte = FailNTimes(fake, failures=2, method="trigger.get")
        cliente = _cliente(transporte, max_retries=4, retry_backoff=0.0)

        resultado = cliente.call("trigger.get", {"output": ["triggerid"]})

        self.assertTrue(resultado)
        self.assertEqual(cliente.retries, 2, "duas falhas => dois retries")
        self.assertEqual(transporte.attempts, 3, "duas falhas + o sucesso")

    def test_backoff_e_progressivo(self):
        esperas: list[float] = []
        fake = FakeZabbix()
        cliente = _cliente(
            FailNTimes(fake, failures=3, method="trigger.get"),
            max_retries=4,
            retry_backoff=2.0,
            sleep=esperas.append,
        )
        cliente.call("trigger.get", {"output": ["triggerid"]})
        self.assertEqual(esperas, [2.0, 4.0, 8.0], "backoff exponencial a partir de 2s")

    def test_backoff_tem_teto(self):
        esperas: list[float] = []
        cliente = _cliente(
            FailNTimes(FakeZabbix(), failures=6, method="trigger.get"),
            max_retries=8,
            retry_backoff=2.0,
            retry_backoff_max=10.0,
            sleep=esperas.append,
        )
        cliente.call("trigger.get", {"output": ["triggerid"]})
        self.assertLessEqual(max(esperas), 10.0)

    def test_erro_definitivo_nao_e_repetido(self):
        """Permissão negada é definitivo: repetir só atrasaria o diagnóstico."""
        tentativas = {"n": 0}

        def transporte(payload, headers):
            tentativas["n"] += 1
            return {"error": {"message": "Application error.", "data": "No permissions to referred object."}}

        cliente = _cliente(transporte, max_retries=4, retry_backoff=0.0)
        with self.assertRaises(ZabbixError):
            cliente.call("trigger.get", {})
        self.assertEqual(tentativas["n"], 1, "erro definitivo não deve ser repetido")
        self.assertEqual(cliente.retries, 0)

    def test_todos_os_status_transitorios_sao_reconhecidos(self):
        for status in (500, 502, 503, 504):
            self.assertIn(status, TRANSIENT_STATUS)

    def test_erro_transitorio_esgota_as_tentativas_e_propaga(self):
        cliente = _cliente(FailNTimes(FakeZabbix(), failures=99, method="trigger.get"),
                           max_retries=2, retry_backoff=0.0)
        with self.assertRaises(ZabbixTransientError):
            cliente.call("trigger.get", {})
        self.assertEqual(cliente.retries, 2)


class TestReducaoDeLote(unittest.TestCase):
    """500 -> falha; 250 -> falha; 125 -> sucesso (redução adaptativa)."""

    def test_lote_grande_e_dividido_ate_o_servidor_aceitar(self):
        ids = [str(i) for i in range(1, 501)]

        def base(payload, headers):
            lote = (payload.get("params") or {}).get("triggerids") or []
            return {"result": [{"triggerid": i} for i in lote]}

        transporte = RejectLargeBatches(base, max_ids=125)
        cliente = _cliente(transporte, page_size=500, min_page_size=25, max_retries=0, retry_backoff=0.0)

        linhas = cliente.get_by_ids("trigger.get", "triggerids", ids, {})

        self.assertEqual(len(linhas), 500, "nenhum objeto pode ser perdido na redução")
        self.assertEqual(transporte.rejected_sizes, [500, 250, 250], "500 -> 250 -> 250 recusados")
        self.assertEqual(max(transporte.accepted_sizes), 125, "só lotes <= 125 passaram")
        self.assertEqual(
            [(r["from"], r["to"]) for r in cliente.batch_reductions],
            [(500, 250), (250, 125), (250, 125)],
        )

    def test_reducao_e_registrada_para_o_relatorio(self):
        def base(payload, headers):
            return {"result": []}

        cliente = _cliente(
            RejectLargeBatches(base, max_ids=1), page_size=4, min_page_size=1, max_retries=0, retry_backoff=0.0
        )
        eventos: list[dict[str, Any]] = []
        cliente.get_by_ids("trigger.get", "triggerids", ["1", "2", "3", "4"], {}, on_page=eventos.append)

        reduzidos = [e for e in eventos if e["event"] == "batch_reduced"]
        self.assertTrue(reduzidos, "a redução precisa aparecer no progresso, não em silêncio")
        self.assertTrue(cliente.batch_reductions)

    def test_objeto_que_falha_sozinho_e_registrado_e_nao_mascarado(self):
        """Um ID que falha até no lote de 1 vira falha registrada — não some."""

        def base(payload, headers):
            lote = (payload.get("params") or {}).get("triggerids") or []
            if "7" in lote:
                raise ZabbixTransientError("HTTP 500: objeto problemático", status=500)
            return {"result": [{"triggerid": i} for i in lote]}

        cliente = _cliente(base, page_size=4, min_page_size=1, max_retries=1, retry_backoff=0.0)
        linhas = cliente.get_by_ids("trigger.get", "triggerids", [str(i) for i in range(1, 9)], {})

        self.assertEqual(len(linhas), 7, "os outros 7 objetos continuam sendo coletados")
        self.assertEqual([f["id"] for f in cliente.failed_objects], ["7"])


    def test_o_piso_de_reducao_impede_dividir_ate_um_objeto(self):
        """Falha sistemática não vira uma requisição por objeto."""
        chamadas: list[int] = []

        def sempre_falha(payload, headers):
            chamadas.append(len((payload.get("params") or {}).get("triggerids") or []))
            raise ZabbixTransientError("HTTP 500: endpoint quebrado", status=500)

        cliente = _cliente(sempre_falha, page_size=100, min_page_size=25, max_retries=0, retry_backoff=0.0)
        cliente.get_by_ids("trigger.get", "triggerids", [str(i) for i in range(1, 101)], {})

        self.assertEqual(min(chamadas), 25, "não se divide abaixo do piso")
        self.assertEqual(len(cliente.failed_objects), 100, "todos os objetos perdidos são registrados")


class TestColetaMultiGrupo(unittest.TestCase):
    """Grupo A + Grupo B => dois escopos coletados, hosts deduplicados."""

    def _coleta(self, **kwargs):
        fake = FakeZabbix()
        cliente = _cliente(fake, trigger_batch_size=50)
        return fake, collect_raw(cliente, **kwargs)

    def test_dois_grupos_de_uma_vez(self):
        _, raw = self._coleta(host_groups=["Servidores Linux", "SIEM"])
        scope = raw.meta["scope"]
        self.assertEqual(scope["kind"], SCOPE_HOST_GROUPS)
        self.assertEqual(sorted(scope["host_groups"]), ["SIEM", "Servidores Linux"])
        self.assertEqual(scope["hosts"], 3)
        self.assertEqual(len(raw.data["triggers"]), 6)

    def test_host_em_dois_grupos_nao_e_coletado_duas_vezes(self):
        # "Infraestrutura" contém os 3 hosts; "SIEM" contém 1 deles de novo.
        fake, raw = self._coleta(host_groups=["Infraestrutura", "SIEM"])
        self.assertEqual(raw.meta["scope"]["hosts"], 3, "hosts repetidos entre grupos são deduplicados")
        ids = [t["triggerid"] for t in raw.data["triggers"]]
        self.assertEqual(len(ids), len(set(ids)), "nenhum trigger duplicado")

    def test_coleta_de_um_grupo_nao_se_declara_ambiente_inteiro(self):
        _, raw = self._coleta(host_groups=["SIEM"])
        self.assertFalse(raw.meta["scope"]["complete_environment"])
        self.assertIn("SIEM", raw.meta["scope"]["label"])

    def test_coleta_global_percorre_grupo_a_grupo(self):
        fake, raw = self._coleta()
        chamadas_host = [p for p in fake.params_called if p["method"] == "host.get" and "groupids" in p["params"]]
        self.assertEqual(len(chamadas_host), 3, "um host.get por grupo do ambiente")
        for chamada in chamadas_host:
            self.assertEqual(len(chamada["params"]["groupids"]), 1)
        self.assertEqual(raw.meta["scope"]["kind"], SCOPE_ENVIRONMENT)
        self.assertTrue(raw.meta["scope"]["complete_environment"])

    def test_nenhuma_requisicao_pede_o_ambiente_inteiro_de_uma_vez(self):
        """A regra mais importante da Fase 2, verificada no log de chamadas."""
        fake, raw = self._coleta()
        for chamada in fake.params_called:
            if chamada["method"] != "trigger.get":
                continue
            params = chamada["params"]
            tem_recorte = any(k in params for k in ("hostids", "triggerids", "groupids", "limit"))
            self.assertTrue(
                tem_recorte,
                f"trigger.get sem recorte de escopo pediria o ambiente inteiro: {params}",
            )

    def test_descoberta_e_barata_e_hidratacao_e_paginada(self):
        fake, raw = self._coleta(host_groups=["Infraestrutura"])
        descobertas = [
            p for p in fake.params_called
            if p["method"] == "trigger.get" and "hostids" in p["params"]
        ]
        self.assertTrue(descobertas)
        for chamada in descobertas:
            self.assertEqual(chamada["params"]["output"], ["triggerid"])
            self.assertNotIn("selectItems", chamada["params"], "descoberta não pode carregar selects caros")

        hidratacoes = [
            p for p in fake.params_called
            if p["method"] == "trigger.get" and "triggerids" in p["params"] and "selectItems" in p["params"]
        ]
        self.assertTrue(hidratacoes, "os triggers precisam ser hidratados por lista de IDs")

    def test_descoberta_tambem_reduz_o_lote_quando_o_servidor_recusa(self):
        """O HTTP 500 pode bater na descoberta, não só na hidratação."""
        transporte = RejectLargeBatches(FakeZabbix(), max_ids=1)
        cliente = _cliente(
            transporte, trigger_batch_size=50, page_size=4, min_page_size=1,
            max_retries=1, retry_backoff=0.0,
        )
        raw = collect_raw(cliente, host_groups=["Infraestrutura"])

        self.assertEqual(len(raw.data["triggers"]), 6, "a coleta precisa terminar mesmo assim")
        self.assertTrue(raw.data["items"], "as fases seguintes também sobrevivem à redução")
        reducoes = [r for r in cliente.batch_reductions if r["method"] == "trigger.get"]
        self.assertTrue(reducoes, "a descoberta precisa dividir o lote de hosts, não morrer")
        self.assertEqual(cliente.failed_objects, [], "dividindo até 1, nada se perde")

    def test_descoberta_que_falha_sem_reducao_possivel_morre_com_erro_claro(self):
        """Falhar é aceitável; falhar em silêncio não é."""
        def sempre_falha(payload, headers):
            if payload["method"] == "trigger.get":
                raise ZabbixTransientError("HTTP 500: trigger.get fora do ar", status=500)
            return FakeZabbix()(payload, headers)

        cliente = _cliente(sempre_falha, max_retries=1, retry_backoff=0.0)
        raw = collect_raw(cliente, host_groups=["SIEM"])

        self.assertEqual(raw.data["triggers"], [])
        self.assertTrue(raw.meta["collection"]["partial"], "sem triggers, a coleta é parcial")
        self.assertTrue(raw.meta["collection"]["failed_objects"])

    def test_grupo_inexistente_e_erro_claro(self):
        with self.assertRaises(ZabbixError) as ctx:
            self._coleta(host_groups=["Grupo Que Nao Existe"])
        self.assertIn("Grupo Que Nao Existe", str(ctx.exception))

    def test_amostra_com_limit_nao_enumera_o_ambiente(self):
        fake, raw = self._coleta(limit=2)
        self.assertEqual(raw.meta["scope"]["kind"], SCOPE_SAMPLE)
        self.assertFalse(raw.meta["scope"]["complete_environment"])
        self.assertEqual(len(raw.data["triggers"]), 2)


class TestMetadadosDaColeta(unittest.TestCase):
    def setUp(self):
        self.fake = FakeZabbix()
        self.cliente = _cliente(self.fake)
        self.raw = collect_raw(self.cliente, host_groups=["SIEM"], page_size=2)

    def test_snapshot_registra_escopo_e_resiliencia(self):
        colecao = self.raw.meta["collection"]
        self.assertEqual(colecao["page_size"], 2)
        self.assertGreater(colecao["pages"], 0)
        self.assertEqual(colecao["retries"], 0)
        self.assertEqual(colecao["failed_objects"], [])
        self.assertFalse(colecao["partial"])
        self.assertIn("duration_seconds", colecao)
        self.assertIn("started_at", colecao)

    def test_filtros_da_fase_1_continuam_no_meta(self):
        self.assertEqual(self.raw.meta["filters"]["host_groups"], ["SIEM"])

    def test_ids_descobertos_ficam_no_meta_para_retomada(self):
        self.assertEqual(len(self.raw.meta["discovered_trigger_ids"]), len(self.raw.data["triggers"]))


class TestColetaParcial(unittest.TestCase):
    def test_falha_definitiva_marca_a_coleta_como_parcial(self):
        fake = FakeZabbix()

        def transporte(payload, headers):
            if payload["method"] == "item.get":
                raise ZabbixTransientError("HTTP 500: item.get indisponível", status=500)
            return fake(payload, headers)

        cliente = _cliente(transporte, max_retries=1, retry_backoff=0.0, page_size=1)
        raw = collect_raw(cliente, host_groups=["SIEM"])

        colecao = raw.meta["collection"]
        self.assertTrue(colecao["partial"], "perder itens torna a coleta parcial")
        self.assertTrue(colecao["failed_objects"])
        self.assertEqual(raw.data["items"], [])
        self.assertTrue(raw.data["triggers"], "o que deu para coletar continua no snapshot")


if __name__ == "__main__":
    unittest.main()
