"""Consolidação de snapshots (item 8 da Fase 2)."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from src.collect import collect_raw
from src.merge import merge_raw_snapshots
from src.normalize import normalize_snapshot
from src.snapshot import list_snapshots, load_raw_snapshot, write_partial_snapshot, write_snapshot
from src.zabbix_client import ZabbixReadOnlyClient
from tests.fixtures.fake_zabbix import FakeZabbix


def _coleta(host_groups):
    cliente = ZabbixReadOnlyClient("https://zabbix.local", api_token="fake-token", transport=FakeZabbix())
    return collect_raw(cliente, host_groups=host_groups)


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.a = _coleta(["Servidores Linux"])
        self.b = _coleta(["SIEM"])
        self.consolidado, self.resumo = merge_raw_snapshots([self.a.to_dict(), self.b.to_dict()])

    def test_objetos_unicos_sao_preservados(self):
        ids_a = {t["triggerid"] for t in self.a.data["triggers"]}
        ids_b = {t["triggerid"] for t in self.b.data["triggers"]}
        ids_merge = {t["triggerid"] for t in self.consolidado.data["triggers"]}
        self.assertEqual(ids_merge, ids_a | ids_b)

    def test_nao_duplica_triggers_hosts_nem_itens(self):
        for colecao in ("triggers", "hosts", "items", "hostgroups", "templates"):
            linhas = self.consolidado.data[colecao]
            campo = {"triggers": "triggerid", "hosts": "hostid", "items": "itemid",
                     "hostgroups": "groupid", "templates": "templateid"}[colecao]
            ids = [linha[campo] for linha in linhas]
            self.assertEqual(len(ids), len(set(ids)), f"{colecao} duplicado no merge")

    def test_o_mesmo_snapshot_duas_vezes_nao_infla_a_base(self):
        uma_vez, _ = merge_raw_snapshots([self.a.to_dict()])
        duas_vezes, resumo = merge_raw_snapshots([self.a.to_dict(), self.a.to_dict()])
        self.assertEqual(
            len(duas_vezes.data["triggers"]), len(uma_vez.data["triggers"]),
            "consolidar o mesmo snapshot duas vezes não pode criar entidades novas",
        )
        self.assertTrue(resumo["duplicates_deduplicated"], "as duplicatas precisam ser contabilizadas")
        self.assertEqual(resumo["conflicts"], [], "o mesmo objeto idêntico não é conflito")

    def test_divergencia_no_mesmo_id_vira_conflito_registrado(self):
        # `to_dict()` compartilha as listas com o RawSnapshot: copiar é
        # obrigatório para alterar só uma das duas versões.
        alterado = copy.deepcopy(self.a.to_dict())
        alterado["data"]["triggers"][0]["priority"] = "5"
        _, resumo = merge_raw_snapshots([self.a.to_dict(), alterado])

        self.assertEqual(len(resumo["conflicts"]), 1)
        conflito = resumo["conflicts"][0]
        self.assertEqual(conflito["collection"], "triggers")
        self.assertIn("priority", conflito["field_hint"])

    def test_estado_de_runtime_nao_conta_como_conflito(self):
        """`value` (OK/PROBLEM) muda o tempo todo e não é mudança de configuração."""
        alterado = copy.deepcopy(self.a.to_dict())
        alterado["data"]["triggers"][0]["value"] = "1"
        _, resumo = merge_raw_snapshots([self.a.to_dict(), alterado])
        self.assertEqual(resumo["conflicts"], [])

    def test_merge_de_grupos_nao_se_declara_ambiente_inteiro(self):
        self.assertFalse(self.resumo["complete_environment"])
        self.assertFalse(self.consolidado.meta["scope"]["complete_environment"])
        self.assertEqual(sorted(self.resumo["host_groups"]), ["SIEM", "Servidores Linux"])

    def test_merge_de_ambientes_completos_continua_completo(self):
        inteiro_a = _coleta([]).to_dict()
        inteiro_b = _coleta([]).to_dict()
        _, resumo = merge_raw_snapshots([inteiro_a, inteiro_b])
        self.assertTrue(resumo["complete_environment"])

    def test_normalizacao_do_merge_ve_o_conjunto_todo(self):
        """Colisões e famílias só aparecem quando se olha os dois grupos juntos."""
        norm_a = normalize_snapshot(self.a)
        norm_b = normalize_snapshot(self.b)
        norm_merge = normalize_snapshot(self.consolidado)
        self.assertEqual(len(norm_merge.alerts), len(norm_a.alerts) + len(norm_b.alerts))
        self.assertGreaterEqual(len(norm_merge.key_index), len(norm_a.key_index))

    def test_fonte_parcial_contamina_o_merge(self):
        parcial = copy.deepcopy(self.b.to_dict())
        parcial["meta"]["collection"] = {**(parcial["meta"].get("collection") or {}), "partial": True}
        _, resumo = merge_raw_snapshots([self.a.to_dict(), parcial])
        self.assertTrue(resumo["partial_sources"])
        self.assertFalse(resumo["complete_environment"])

    def test_merge_sem_fontes_e_erro(self):
        with self.assertRaises(ValueError):
            merge_raw_snapshots([])


class TestSnapshotsIndependentes(unittest.TestCase):
    def test_coletas_diferentes_geram_diretorios_diferentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = _coleta(["Servidores Linux"])
            b = _coleta(["SIEM"])
            dir_a = write_snapshot(tmp, a, normalize_snapshot(a))["snapshot_dir"]
            dir_b = write_snapshot(tmp, b, normalize_snapshot(b))["snapshot_dir"]

            self.assertNotEqual(dir_a, dir_b)
            self.assertTrue(dir_a.is_dir(), "a coleta anterior não pode ser destruída")
            self.assertIn("servidores-linux", dir_a.name)
            self.assertIn("siem", dir_b.name)

    def test_snapshot_parcial_nao_corrompe_a_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            boa = _coleta(["SIEM"])
            dir_boa = write_snapshot(tmp, boa, normalize_snapshot(boa))["snapshot_dir"]
            triggers_antes = len(load_raw_snapshot(dir_boa)["data"]["triggers"])

            parcial = _coleta(["SIEM"])
            parcial.data["triggers"] = parcial.data["triggers"][:1]
            dir_parcial = write_partial_snapshot(tmp, parcial, "HTTP 500 na página 3")

            self.assertNotEqual(dir_parcial, dir_boa)
            self.assertEqual(len(load_raw_snapshot(dir_boa)["data"]["triggers"]), triggers_antes)
            self.assertTrue(load_raw_snapshot(dir_parcial)["meta"]["collection"]["partial"])
            self.assertIn("parcial", dir_parcial.name)

    def test_listagem_ignora_diretorios_sem_snapshot_bruto(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "snapshots" / "lixo").mkdir(parents=True)
            a = _coleta(["SIEM"])
            write_snapshot(tmp, a, normalize_snapshot(a))
            nomes = [d.name for d in list_snapshots(tmp)]
            self.assertNotIn("lixo", nomes)
            self.assertEqual(len(nomes), 1)


if __name__ == "__main__":
    unittest.main()
