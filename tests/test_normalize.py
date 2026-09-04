"""Testes unitários das funções de normalização."""

import unittest

from src.normalize import _enum, _prune_inventory, analyze_keys, build_stats, infer_generic_rules


def _alerta(alert_key: str, triggerid: str, signature: str, host: str = "srv-01") -> dict:
    return {
        "alert_key": alert_key,
        "alert_key_strategy": "host+description",
        "alert_key_scope": {"type": "host", "name": host, "id": "1"},
        "zabbix": {
            "triggerid": triggerid,
            "description_raw": "Serviço parado",
            "description_normalized": "servico-parado",
            "expression_signature": signature,
            "expression_expanded": signature,
            "priority": {"value": "4", "name": "High"},
            "status": {"value": "0", "name": "enabled"},
            "source_template": None,
            "templated": False,
            "discovered": False,
            "comments": "",
            "tags": [],
            "dependencies": [],
            "host": {"host": host, "name": host, "hostid": host},
        },
    }


class TestEnums(unittest.TestCase):
    def test_valor_conhecido(self):
        self.assertEqual(_enum("4", {"4": "High"}), {"value": "4", "name": "High"})

    def test_valor_desconhecido_nao_quebra(self):
        self.assertEqual(_enum("99", {"4": "High"})["name"], "unknown")
        self.assertEqual(_enum(None, {})["value"], "")


class TestInventario(unittest.TestCase):
    def test_mantem_somente_campos_uteis_e_preenchidos(self):
        inventario = {"os": "Ubuntu 22.04", "location": "", "campo_irrelevante": "x", "contact": " NOC "}
        self.assertEqual(_prune_inventory(inventario), {"os": "Ubuntu 22.04", "contact": "NOC"})

    def test_inventario_desabilitado_vira_dicionario_vazio(self):
        self.assertEqual(_prune_inventory([]), {})
        self.assertEqual(_prune_inventory(None), {})


class TestAnaliseDeChaves(unittest.TestCase):
    def test_mesma_assinatura_em_hosts_diferentes_nao_e_colisao(self):
        # Escopo de template: N hosts sob a mesma chave é o objetivo do desenho.
        alertas = [
            _alerta("tmpl|servico-parado", "1", "last(/{HOST}/proc.num[nginx])=0", "srv-01"),
            _alerta("tmpl|servico-parado", "2", "last(/{HOST}/proc.num[nginx])=0", "srv-02"),
        ]
        for alerta in alertas:
            alerta["alert_key_scope"] = {"type": "template", "name": "Linux by Zabbix agent", "id": "10001"}
        index, colisoes = analyze_keys(alertas)
        self.assertEqual(colisoes, [])
        self.assertEqual(index["tmpl|servico-parado"]["count"], 2)
        self.assertEqual(index["tmpl|servico-parado"]["hosts"], ["srv-01", "srv-02"])

    def test_assinaturas_diferentes_na_mesma_chave_sao_colisao(self):
        alertas = [
            _alerta("wazuh|servico-parado", "1", "last(/{HOST}/proc.num[filebeat])=0"),
            _alerta("wazuh|servico-parado", "2", "last(/{HOST}/proc.num[wazuh-manager])=0"),
        ]
        index, colisoes = analyze_keys(alertas)
        self.assertEqual(len(colisoes), 1)
        self.assertTrue(index["wazuh|servico-parado"]["collision"])
        self.assertEqual(len(colisoes[0]["suggested_keys"]), 2)
        self.assertIn("#", colisoes[0]["suggested_key_pattern"])

    def test_hosts_distintos_com_o_mesmo_slug_sao_colisao_de_escopo(self):
        # "Vibe - Zabbix-Proxy" e "Vibe - Zabbix Proxy" geram o mesmo slug, mas
        # são hosts diferentes: a fusão não pode passar despercebida.
        a = _alerta("vibe-zabbix-proxy|running-out-of-inodes", "1", "last(/{HOST}/vfs.fs.inode[/,pfree])<20")
        a["zabbix"]["host"] = {"host": "Vibe - Zabbix-Proxy", "name": "Vibe - Zabbix-Proxy", "hostid": "10693"}
        b = _alerta("vibe-zabbix-proxy|running-out-of-inodes", "2", "last(/{HOST}/vfs.fs.inode[/,pfree])<20")
        b["zabbix"]["host"] = {"host": "Vibe - Zabbix Proxy", "name": "Vibe - Zabbix Proxy", "hostid": "10777"}

        index, colisoes = analyze_keys([a, b])
        self.assertEqual(len(colisoes), 1)
        self.assertIn("escopo_ambiguo", colisoes[0]["reasons"])
        self.assertEqual(colisoes[0]["distinct_hostids"], 2)
        self.assertEqual(len(colisoes[0]["suggested_keys"]), 2)
        self.assertTrue(index["vibe-zabbix-proxy|running-out-of-inodes"]["collision"])

    def test_mesmo_host_com_triggers_iguais_nao_e_colisao_de_escopo(self):
        a = _alerta("host-x|servico-parado", "1", "sig-igual")
        b = _alerta("host-x|servico-parado", "2", "sig-igual")
        _, colisoes = analyze_keys([a, b])
        self.assertEqual(colisoes, [])

    def test_escopo_de_template_com_varios_hosts_nao_e_colisao(self):
        a = _alerta("tmpl|disco-cheio", "1", "sig-igual", host="srv-01")
        b = _alerta("tmpl|disco-cheio", "2", "sig-igual", host="srv-02")
        for alerta, hostid in ((a, "1"), (b, "2")):
            alerta["alert_key_scope"] = {"type": "template", "name": "Linux by Zabbix agent", "id": "10001"}
            alerta["zabbix"]["host"]["hostid"] = hostid
        _, colisoes = analyze_keys([a, b])
        self.assertEqual(colisoes, [], "template compartilhado entre hosts é o comportamento desejado")

    def test_regra_generica_inferida_agrupa_o_mesmo_trigger_em_varios_hosts(self):
        # Sem acesso a templates, cada host vira uma chave; a inferência mostra
        # que na verdade é uma regra só, replicada.
        alertas = [
            _alerta(f"srv-{i:02d}|servico-parado", str(i), "last(/{HOST}/proc.num[nginx])=0", f"srv-{i:02d}")
            for i in range(1, 6)
        ]
        resultado = infer_generic_rules(alertas)
        self.assertEqual(resultado["summary"]["estimated_distinct_procedures"], 1)
        self.assertEqual(resultado["summary"]["rules_spanning_multiple_hosts"], 1)
        self.assertEqual(resultado["summary"]["alerts_in_multi_host_rules"], 5)
        self.assertEqual(resultado["summary"]["duplicate_alert_keys_avoidable"], 4)
        self.assertEqual(resultado["top"][0]["hosts"], 5)

    def test_regras_tecnicamente_diferentes_nao_sao_agrupadas(self):
        alertas = [
            _alerta("srv-01|servico-parado", "1", "last(/{HOST}/proc.num[nginx])=0", "srv-01"),
            _alerta("srv-02|servico-parado", "2", "last(/{HOST}/proc.num[postgres])=0", "srv-02"),
        ]
        resultado = infer_generic_rules(alertas)
        self.assertEqual(resultado["summary"]["estimated_distinct_procedures"], 2)
        self.assertEqual(resultado["summary"]["rules_spanning_multiple_hosts"], 0)
        self.assertEqual(resultado["top"], [])

    def test_estatisticas_agregadas(self):
        alertas = [
            _alerta("a|x", "1", "sig-1"),
            _alerta("a|x", "2", "sig-2"),
            _alerta("b|y", "3", "sig-3"),
        ]
        index, colisoes = analyze_keys(alertas)
        stats = build_stats(alertas, index, colisoes)
        self.assertEqual(stats["alerts"], 3)
        self.assertEqual(stats["unique_alert_keys"], 2)
        self.assertEqual(stats["alert_key_collisions"], 1)
        self.assertEqual(stats["without_comments"], 3)
        self.assertEqual(stats["by_priority"], {"High": 3})


if __name__ == "__main__":
    unittest.main()
