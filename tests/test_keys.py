"""Testes de alert_key e source_hash."""

import unittest

from src.keys import (
    build_alert_key,
    compute_source_hash,
    expression_signature,
    normalize_description,
    slugify,
    strip_accents,
)


class TestNormalization(unittest.TestCase):
    def test_remove_acentos_e_caixa(self):
        self.assertEqual(strip_accents("Espaço em disco CRÍTICO"), "Espaco em disco CRITICO")
        self.assertEqual(slugify("  Espaço  em   disco CRÍTICO  "), "espaco-em-disco-critico")

    def test_diferencas_irrelevantes_produzem_a_mesma_chave(self):
        variantes = [
            "Serviço parado",
            "SERVIÇO PARADO",
            "  Servico   parado ",
            "Serviço, parado!",
        ]
        chaves = {build_alert_key("wazuh", v) for v in variantes}
        self.assertEqual(len(chaves), 1, chaves)

    def test_macros_nao_entram_na_chave(self):
        self.assertEqual(
            normalize_description("Disk space is low (used > {$LIMIT})"),
            normalize_description("Disk space is low (used > {$OUTRO.LIMITE})"),
        )

    def test_descricao_apenas_de_macros_continua_deterministica(self):
        chave1 = build_alert_key("t", "{HOST.NAME} {ITEM.VALUE}", triggerid="1")
        chave2 = build_alert_key("t", "{HOST.NAME} {ITEM.VALUE}", triggerid="1")
        self.assertEqual(chave1, chave2)
        self.assertTrue(chave1.startswith("t|"))

    def test_formato_escopo_pipe_descricao(self):
        chave = build_alert_key("Template Linux Disk", "Disk space is critically low")
        self.assertEqual(chave, "template-linux-disk|disk-space-is-critically-low")


class TestExpressionSignature(unittest.TestCase):
    def test_hosts_diferentes_mesma_assinatura(self):
        a = expression_signature("last(/srv-01/vfs.fs.size[/,pfree])<20", ("srv-01",))
        b = expression_signature("last(/srv-02/vfs.fs.size[/,pfree])<20", ("srv-02",))
        self.assertEqual(a, b)

    def test_itens_diferentes_assinaturas_diferentes(self):
        a = expression_signature("last(/wazuh/proc.num[filebeat])=0", ("wazuh",))
        b = expression_signature("last(/wazuh/proc.num[wazuh-manager])=0", ("wazuh",))
        self.assertNotEqual(a, b)


class TestSourceHash(unittest.TestCase):
    BASE = {
        "description_raw": "Disk space is critically low",
        "expression_signature": "last(/{HOST}/vfs.fs.size[/,pfree])<20",
        "priority": "4",
        "tags": ["scope=capacity"],
        "items": ["vfs.fs.size[/,pfree]|%|0"],
        "host": "srv-01",
        "host_groups": ["Infraestrutura"],
        "templates": ["Linux by Zabbix agent"],
    }

    def test_deterministico(self):
        self.assertEqual(compute_source_hash(dict(self.BASE)), compute_source_hash(dict(self.BASE)))
        self.assertTrue(compute_source_hash(self.BASE).startswith("sha256:"))

    def test_mudanca_tecnica_muda_o_hash(self):
        alterado = {**self.BASE, "priority": "5"}
        self.assertNotEqual(compute_source_hash(self.BASE), compute_source_hash(alterado))

    def test_campos_fora_do_escopo_nao_mudam_o_hash(self):
        # triggerid, value (OK/PROBLEM) e status não entram no hash técnico.
        ruido = {**self.BASE, "triggerid": "999", "value": "1", "status": "1"}
        self.assertEqual(compute_source_hash(self.BASE), compute_source_hash(ruido))


if __name__ == "__main__":
    unittest.main()
