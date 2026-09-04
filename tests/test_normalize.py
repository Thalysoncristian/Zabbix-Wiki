"""Testes unitários das funções de normalização."""

import unittest

from src.normalize import (
    _enum,
    _prune_inventory,
    analyze_keys,
    build_stats,
    infer_alert_families,
    infer_generic_rules,
)


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

    def test_triggers_distintos_no_mesmo_host_sao_colisao_mesmo_com_assinatura_igual(self):
        # Caso real: dois triggers "Domain Expiry ... will expire soon" no mesmo
        # host, um avisando com 30 dias e outro com 7. A assinatura troca macros
        # por {MACRO}, então as duas ficam idênticas e a fusão passaria batida.
        a = _alerta("host-x|servico-parado", "1", "sig-igual")
        b = _alerta("host-x|servico-parado", "2", "sig-igual")
        _, colisoes = analyze_keys([a, b])
        self.assertEqual(len(colisoes), 1)
        self.assertEqual(colisoes[0]["reasons"], ["duplicado_no_host"])
        self.assertNotIn("escopo_ambiguo", colisoes[0]["reasons"], "é o mesmo host, não ambiguidade de escopo")
        self.assertEqual(colisoes[0]["duplicated_on_hosts"], {"srv-01": ["1", "2"]})

    def test_um_trigger_por_host_nao_e_duplicata(self):
        a = _alerta("tmpl|disco-cheio", "1", "sig-igual", host="srv-01")
        b = _alerta("tmpl|disco-cheio", "2", "sig-igual", host="srv-02")
        for alerta in (a, b):
            alerta["alert_key_scope"] = {"type": "template", "name": "Linux by Zabbix agent", "id": "10001"}
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


class TestFamiliasDeAlertas(unittest.TestCase):
    """Famílias: o nível em que o procedimento operacional costuma ser único."""

    @staticmethod
    def _lld(alert_key: str, triggerid: str, descricao: str, prototipo: str, regra: str, host: str) -> dict:
        alerta = _alerta(alert_key, triggerid, f"last(/{{HOST}}/service.info[{descricao}])<>0", host)
        alerta["zabbix"].update(
            {
                "description_raw": descricao,
                "description_normalized": descricao.lower().replace(" ", "-"),
                "discovered": True,
                "prototype_description": prototipo,
                "discovery_rule": {"itemid": "1", "name": regra, "key_": "service.discovery"},
            }
        )
        return alerta

    def test_alertas_de_lld_colapsam_na_familia_do_prototipo(self):
        # 3 serviços x 2 hosts = 6 alertas, 6 chaves distintas, 1 família.
        alertas = [
            self._lld(f"{host}|{svc}", f"{i}", svc, '"{#SERVICE.NAME}" is not running', "Windows services discovery", host)
            for i, (host, svc) in enumerate(
                [(h, s) for h in ("srv-01", "srv-02") for s in ("AudioSrv", "BFE", "SSMAgent")]
            )
        ]
        familias = infer_alert_families(alertas)
        self.assertEqual(familias["summary"]["families"], 1)
        self.assertEqual(familias["summary"]["alerts"], 6)
        self.assertEqual(familias["top"][0]["alerts"], 6)
        self.assertEqual(familias["top"][0]["alert_keys"], 6)
        self.assertEqual(familias["top"][0]["hosts"], 2)
        self.assertTrue(familias["top"][0]["origin"].startswith("LLD:"))

    def test_regras_de_lld_diferentes_sao_familias_diferentes(self):
        alertas = [
            self._lld("h|a", "1", "AudioSrv", '"{#SERVICE.NAME}" is not running', "Windows services", "srv-01"),
            self._lld("h|b", "2", "/var", "{#FSNAME}: Disk space low", "Filesystem discovery", "srv-01"),
        ]
        self.assertEqual(infer_alert_families(alertas)["summary"]["families"], 2)

    def test_triggers_diretos_agrupam_pela_regra_inferida(self):
        alertas = [
            _alerta("srv-01|servico-parado", "1", "last(/{HOST}/proc.num[nginx])=0", "srv-01"),
            _alerta("srv-02|servico-parado", "2", "last(/{HOST}/proc.num[nginx])=0", "srv-02"),
        ]
        familias = infer_alert_families(alertas)
        self.assertEqual(familias["summary"]["families"], 1)
        self.assertEqual(familias["top"][0]["origin"], "trigger direto")
