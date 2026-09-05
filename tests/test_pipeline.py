"""Pipeline completo (coleta -> normalização -> snapshot) contra um Zabbix falso."""

import json
import tempfile
import unittest
from pathlib import Path

from src.collect import collect_raw
from src.normalize import normalize_snapshot
from src.report import build_report, format_report_lines
from src.snapshot import write_snapshot
from src.zabbix_client import ZabbixError, ZabbixReadOnlyClient
from tests.fixtures.fake_zabbix import FakeZabbix


def _run(version: str = "7.0.0"):
    fake = FakeZabbix(version=version)
    client = ZabbixReadOnlyClient("https://zabbix.local", api_token="fake-token", transport=fake)
    raw = collect_raw(client)
    return fake, client, raw, normalize_snapshot(raw)


class TestPaginacaoPorHost(unittest.TestCase):
    """A coleta completa pagina o trigger.get em lotes de hosts.

    Sem isso, ambientes grandes devolvem HTTP 500 (timeout/memória) quando se
    pede os triggers de milhares de hosts numa única chamada.
    """

    def _coleta(self, trigger_batch_size: int, **kwargs):
        fake = FakeZabbix()
        client = ZabbixReadOnlyClient(
            "https://zabbix.local",
            api_token="fake-token",
            trigger_batch_size=trigger_batch_size,
            transport=fake,
        )
        return fake, collect_raw(client, **kwargs)

    def test_um_trigger_get_por_lote_de_hosts(self):
        fake, raw = self._coleta(trigger_batch_size=1)
        # 3 hosts / lote de 1 => pelo menos 3 chamadas de coleta de triggers.
        chamadas_host = [p for p in fake.params_called if p["method"] == "trigger.get" and "hostids" in p["params"]]
        self.assertEqual(len(chamadas_host), 3)
        for chamada in chamadas_host:
            self.assertEqual(len(chamada["params"]["hostids"]), 1)
        self.assertEqual(len(raw.data["triggers"]), 6)

    def test_lote_maior_faz_menos_chamadas_e_traz_o_mesmo_resultado(self):
        fake, raw = self._coleta(trigger_batch_size=50)
        chamadas_host = [p for p in fake.params_called if p["method"] == "trigger.get" and "hostids" in p["params"]]
        self.assertEqual(len(chamadas_host), 1)
        self.assertEqual(len(raw.data["triggers"]), 6)

    def test_triggers_nao_duplicam_entre_lotes(self):
        _, raw = self._coleta(trigger_batch_size=1)
        ids = [t["triggerid"] for t in raw.data["triggers"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_limit_continua_em_chamada_unica(self):
        fake, raw = self._coleta(trigger_batch_size=1, limit=2)
        chamadas_host = [p for p in fake.params_called if p["method"] == "trigger.get" and "hostids" in p["params"]]
        self.assertEqual(chamadas_host, [], "--limit não deve paginar por host")
        self.assertEqual(len(raw.data["triggers"]), 2)

    def test_filtro_de_grupo_restringe_os_hosts_paginados(self):
        fake, raw = self._coleta(trigger_batch_size=1, host_groups=["SIEM"])
        chamadas_host = [p for p in fake.params_called if p["method"] == "trigger.get" and "hostids" in p["params"]]
        # Só o host do grupo SIEM (wazuh, hostid 10503) entra no escopo.
        self.assertEqual(len(chamadas_host), 1)
        self.assertEqual(chamadas_host[0]["params"]["hostids"], ["10503"])


class TestColeta(unittest.TestCase):
    def setUp(self):
        self.fake, self.client, self.raw, self.norm = _run()

    def test_apenas_metodos_de_leitura_foram_chamados(self):
        for method in self.fake.methods_called:
            self.assertTrue(method.endswith(".get") or method == "apiinfo.version", method)

    def test_relacionamentos_resolvidos(self):
        self.assertEqual(len(self.raw.data["triggers"]), 6)
        self.assertEqual(len(self.raw.data["hosts"]), 3)
        self.assertEqual(len(self.raw.data["hostgroups"]), 3)
        self.assertEqual(len(self.raw.data["templates"]), 2)
        self.assertEqual(len(self.raw.data["items"]), 6)

    def test_snapshot_bruto_guarda_o_que_veio_da_api(self):
        payload = self.raw.to_dict()
        self.assertTrue(payload["meta"]["read_only"])
        self.assertEqual(payload["meta"]["zabbix_version"], "7.0.0")
        self.assertTrue(payload["api_calls"])
        self.assertIn("triggers", payload["data"])

    def test_autenticacao_por_campo_auth_em_versoes_antigas(self):
        fake, client, raw, _ = _run(version="6.0.20")
        self.assertEqual(client.auth_style, "auth_field")
        self.assertEqual(len(raw.data["triggers"]), 6)

    def test_credencial_invalida_gera_erro(self):
        client = ZabbixReadOnlyClient("https://zabbix.local", api_token="errado", transport=FakeZabbix())
        with self.assertRaises(ZabbixError):
            collect_raw(client)


class TestAlertasNormalizados(unittest.TestCase):
    def setUp(self):
        _, _, self.raw, self.norm = _run()
        self.por_trigger = {a["zabbix"]["triggerid"]: a for a in self.norm.alerts}

    def test_um_alerta_por_trigger(self):
        self.assertEqual(len(self.norm.alerts), 6)

    def test_json_e_autocontido(self):
        for alerta in self.norm.alerts:
            zbx = alerta["zabbix"]
            self.assertTrue(zbx["host"]["name"], "host sem nome resolvido")
            self.assertTrue(zbx["host_groups"], "grupos não resolvidos")
            self.assertTrue(all(isinstance(g, str) for g in zbx["host_groups"]))
            self.assertTrue(all(isinstance(t, str) for t in zbx["templates"]))
            self.assertTrue(zbx["source_hash"].startswith("sha256:"))
            self.assertTrue(zbx["collected_at"])

    def test_trigger_de_template_compartilha_a_mesma_chave_entre_hosts(self):
        a, b = self.por_trigger["100"], self.por_trigger["101"]
        self.assertEqual(a["alert_key"], b["alert_key"])
        self.assertEqual(a["alert_key_strategy"], "template+description")
        self.assertEqual(a["alert_key_scope"]["type"], "template")
        self.assertFalse(a["alert_key_collision"], "hosts diferentes no mesmo template não são colisão")

    def test_trigger_de_lld_usa_a_descricao_do_prototipo(self):
        alerta = self.por_trigger["200"]
        self.assertEqual(alerta["alert_key_strategy"], "prototype+description")
        self.assertTrue(alerta["zabbix"]["discovered"])
        self.assertEqual(alerta["zabbix"]["prototype_description"], "{#FSNAME}: Disk space is critically low")
        self.assertEqual(alerta["alert_key_scope"]["name"], "Linux by Zabbix agent")

    def test_trigger_local_usa_o_host_como_escopo(self):
        alerta = self.por_trigger["400"]
        self.assertEqual(alerta["alert_key_strategy"], "host+description")
        self.assertEqual(alerta["alert_key_scope"]["type"], "host")

    def test_dependencias_com_nomes_resolvidos(self):
        deps = self.por_trigger["200"]["zabbix"]["dependencies"]
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["description"], "Wazuh: fila de eventos ACIMA do limite")
        self.assertEqual(deps[0]["host"], "Vibe - Wazuh SIEM")

    def test_itens_do_trigger_com_unidade(self):
        itens = self.por_trigger["100"]["zabbix"]["items"]
        self.assertEqual(itens[0]["key_"], "vfs.fs.size[/,pfree]")
        self.assertEqual(itens[0]["units"], "%")

    def test_inventario_vazio_vira_dicionario_vazio(self):
        self.assertEqual(self.por_trigger["101"]["zabbix"]["host"]["inventory"], {})

    def test_colisao_detectada_e_relatada(self):
        self.assertEqual(len(self.norm.collisions), 1)
        colisao = self.norm.collisions[0]
        self.assertEqual(colisao["alert_key"], "wazuh|servico-parado")
        self.assertEqual(colisao["distinct_signatures"], 2)
        self.assertEqual(len(colisao["suggested_keys"]), 2)
        for triggerid in ("401", "402"):
            alerta = self.por_trigger[triggerid]
            self.assertTrue(alerta["alert_key_collision"])
            self.assertTrue(alerta["alert_key_suggested"].startswith("wazuh|servico-parado#"))

    def test_chaves_sugeridas_desambiguam(self):
        sugeridas = {self.por_trigger["401"]["alert_key_suggested"], self.por_trigger["402"]["alert_key_suggested"]}
        self.assertEqual(len(sugeridas), 2)

    def test_hash_ignora_estado_runtime(self):
        # 100 e 101 são o mesmo trigger de template em hosts distintos e estão em
        # estados diferentes (OK x PROBLEM); só o host deve diferenciar o hash.
        a, b = self.por_trigger["100"]["zabbix"], self.por_trigger["101"]["zabbix"]
        self.assertNotEqual(a["value"]["name"], b["value"]["name"])
        self.assertNotEqual(a["source_hash"], b["source_hash"])  # hosts diferentes
        self.assertEqual(a["expression_signature"], b["expression_signature"])

    def test_estatisticas(self):
        stats = self.norm.stats
        self.assertEqual(stats["alerts"], 6)
        self.assertEqual(stats["unique_alert_keys"], 4)
        self.assertEqual(stats["alert_key_collisions"], 1)
        self.assertEqual(stats["templated"], 2)
        self.assertEqual(stats["discovered"], 1)


class TestSnapshotEmDisco(unittest.TestCase):
    def test_arquivos_gerados_e_snapshots_nao_se_sobrescrevem(self):
        _, _, raw, norm = _run()
        with tempfile.TemporaryDirectory() as tmp:
            primeiro = write_snapshot(tmp, raw, norm)
            segundo = write_snapshot(tmp, raw, norm)
            self.assertNotEqual(primeiro["snapshot_dir"], segundo["snapshot_dir"])

            base = primeiro["snapshot_dir"]
            self.assertTrue((base / "raw" / "zabbix_raw.json").is_file())
            self.assertTrue((base / "normalized" / "alerts.json").is_file())
            self.assertTrue((base / "normalized" / "alert_keys.json").is_file())
            self.assertTrue((base / "normalized" / "collisions.json").is_file())

            alerts = json.loads((base / "normalized" / "alerts.json").read_text(encoding="utf-8"))
            self.assertEqual(alerts["count"], 6)
            self.assertEqual(len(alerts["alerts"]), 6)

            relatorio = build_report(raw, norm, primeiro)

            # `--full` preserva o detalhamento linha a linha da ETAPA 1.
            completo = "\n".join(format_report_lines(relatorio, full=True))
            for esperado in (
                "✓ Conectado ao Zabbix",
                "✓ 6 triggers encontrados",
                "✓ 3 hosts resolvidos",
                "✓ 3 host groups resolvidos",
                "✓ 2 templates resolvidos",
                "✓ 6 itens relacionados resolvidos",
                "✓ Snapshot bruto salvo",
                "✓ Alertas normalizados salvos",
                "✓ 4 alertas únicos",
                "✓ 1 possíveis colisões de alert_key",
            ):
                self.assertIn(esperado, completo)

            # O compacto diz as mesmas coisas em menos linhas — e cabe na tela.
            compacto = format_report_lines(relatorio)
            texto = "\n".join(compacto)
            for esperado in (
                "✓ Conectado ao Zabbix",
                "✓ 6 triggers encontrados",
                "✓ 3 hosts · 3 grupos · 2 templates · 6 itens",
                "✓ 4 alertas únicos",
                "✓ 1 possíveis colisões de alert_key",
                "Snapshot completo em:",
            ):
                self.assertIn(esperado, texto)
            self.assertLess(len(compacto), len(format_report_lines(relatorio, full=True)))

    def test_snapshot_nao_vaza_credenciais(self):
        _, _, raw, norm = _run()
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_snapshot(tmp, raw, norm)
            conteudo = Path(paths["raw"]).read_text(encoding="utf-8")
            self.assertNotIn("fake-token", conteudo)


if __name__ == "__main__":
    unittest.main()
