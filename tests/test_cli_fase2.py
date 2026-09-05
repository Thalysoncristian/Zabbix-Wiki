"""CLI da Fase 2: multi-grupo, page-size, split, merge e resume."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

from src import cli
from src.config import Settings
from src.zabbix_client import ZabbixReadOnlyClient, ZabbixTransientError
from tests.fixtures.fake_zabbix import FakeZabbix


class _Ambiente:
    """Roda a CLI contra o Zabbix falso, num diretório de saída temporário."""

    def __init__(self, tmp: str, transport: Any | None = None, **settings_kwargs: Any):
        self.tmp = tmp
        self.transport = transport or FakeZabbix()
        self.settings = Settings(
            url="https://zabbix.local", api_token="fake-token", output_dir=tmp, **settings_kwargs
        )

    def _client(self, settings, transport=None):
        return ZabbixReadOnlyClient(
            settings.url,
            api_token=settings.api_token,
            page_size=settings.page_size,
            max_retries=settings.max_retries,
            retry_backoff=0.0,
            transport=self.transport,
            sleep=lambda _s: None,
        )

    def run(self, argv: list[str]) -> tuple[int, str]:
        buffer = io.StringIO()
        with mock.patch.object(cli, "load_settings", return_value=self.settings), mock.patch.object(
            ZabbixReadOnlyClient, "from_settings", staticmethod(self._client)
        ), redirect_stdout(buffer):
            codigo = cli.main(argv)
        return codigo, buffer.getvalue()

    @property
    def snapshots(self) -> list[Path]:
        raiz = Path(self.tmp) / "snapshots"
        return sorted(d for d in raiz.iterdir() if d.is_dir() and not d.is_symlink())


class TestColetaPorGrupo(unittest.TestCase):
    def test_um_grupo(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, saida = amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertIn("Escopo da coleta : 1 grupo(s) de hosts: SIEM", saida)
            self.assertIn("não o ambiente inteiro", saida)
            self.assertEqual(len(amb.snapshots), 1)
            self.assertIn("siem", amb.snapshots[0].name)

    def test_varios_grupos_repetindo_a_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, saida = amb.run(
                ["collect", "--host-group", "SIEM", "--host-group", "Servidores Linux", "--examples", "0"]
            )
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertIn("SIEM", saida)
            self.assertIn("Servidores Linux", saida)
            relatorio = json.loads((amb.snapshots[0] / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(relatorio["scope"]["host_groups"]), ["SIEM", "Servidores Linux"])

    def test_varios_grupos_separados_por_virgula(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, _ = amb.run(["collect", "--host-group", "SIEM,Servidores Linux", "--examples", "0"])
            self.assertEqual(codigo, cli.EXIT_OK)
            relatorio = json.loads((amb.snapshots[0] / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(relatorio["scope"]["host_groups"]), ["SIEM", "Servidores Linux"])

    def test_split_by_group_gera_um_snapshot_por_grupo(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, saida = amb.run(
                ["collect", "--host-group", "SIEM,Servidores Linux", "--split-by-group", "--examples", "0"]
            )
            self.assertEqual(codigo, cli.EXIT_OK)
            nomes = [d.name for d in amb.snapshots]
            self.assertEqual(len(nomes), 2, f"esperado um snapshot por grupo, veio {nomes}")
            self.assertTrue(any("siem" in n for n in nomes))
            self.assertTrue(any("servidores-linux" in n for n in nomes))
            self.assertIn("python main.py merge --last 2", saida)

    def test_split_com_merge_consolida_no_fim(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, saida = amb.run(
                ["collect", "--host-group", "SIEM,Servidores Linux",
                 "--split-by-group", "--merge", "--examples", "0"]
            )
            self.assertEqual(codigo, cli.EXIT_OK)
            nomes = [d.name for d in amb.snapshots]
            self.assertEqual(len(nomes), 3, "dois snapshots por grupo + o consolidado")
            self.assertTrue(any("consolidado" in n for n in nomes))
            self.assertIn("Consolidação", saida)

    def test_split_sem_grupo_e_erro_de_configuracao(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, _ = amb.run(["collect", "--split-by-group"])
            self.assertEqual(codigo, cli.EXIT_CONFIG)

    def test_coleta_global_continua_gerando_um_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, saida = amb.run(["collect", "--examples", "0"])
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertEqual(len(amb.snapshots), 1)
            self.assertIn("Escopo da coleta : ambiente inteiro", saida)


class TestPageSizeNaCli(unittest.TestCase):
    def test_page_size_chega_ate_a_paginacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, saida = amb.run(["collect", "--page-size", "2", "--examples", "0"])
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertIn("tamanho de página             : 2", saida)

            lotes = [
                len(p["params"]["triggerids"])
                for p in amb.transport.params_called
                if p["method"] == "trigger.get" and isinstance(p["params"].get("triggerids"), list)
            ]
            self.assertTrue(lotes)
            self.assertLessEqual(max(lotes), 2, "nenhuma página pode exceder o --page-size")

    def test_progresso_mostra_paginas_e_porcentagem(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            _, saida = amb.run(["collect", "--page-size", "2", "--examples", "0"])
            self.assertIn("triggers: página 1", saida)
            self.assertIn("(100%)", saida)


class TestMergeNaCli(unittest.TestCase):
    def test_consolida_coletas_de_dias_diferentes(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])
            amb.run(["collect", "--host-group", "Servidores Linux", "--examples", "0"])

            codigo, saida = amb.run(["merge"])
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertIn("Consolidando 2 snapshots", saida)
            self.assertIn("Consolidação", saida)

            consolidados = [d for d in amb.snapshots if "consolidado" in d.name]
            self.assertEqual(len(consolidados), 1)
            bruto = json.loads((consolidados[0] / "raw" / "zabbix_raw.json").read_text(encoding="utf-8"))
            ids = [t["triggerid"] for t in bruto["data"]["triggers"]]
            self.assertEqual(len(ids), len(set(ids)), "o merge não pode duplicar triggers")

    def test_merge_exige_pelo_menos_dois_snapshots(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])
            codigo, _ = amb.run(["merge"])
            self.assertEqual(codigo, cli.EXIT_CONFIG)

    def test_merge_nao_reconsolida_um_consolidado(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])
            amb.run(["collect", "--host-group", "Servidores Linux", "--examples", "0"])
            amb.run(["merge"])
            codigo, saida = amb.run(["merge"])
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertIn("Consolidando 2 snapshots", saida, "o consolidado anterior não entra como fonte")


class TestResume(unittest.TestCase):
    def test_resume_reaproveita_os_ids_da_coleta_anterior(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])
            codigo, saida = amb.run(["collect", "--host-group", "SIEM", "--resume", "--examples", "0"])
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertIn("Retomando a partir de", saida)

    def test_resume_sem_coleta_anterior_apenas_coleta(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            codigo, saida = amb.run(["collect", "--host-group", "SIEM", "--resume", "--examples", "0"])
            self.assertEqual(codigo, cli.EXIT_OK)
            self.assertNotIn("Retomando a partir de", saida)

    def test_resume_so_reaproveita_o_mesmo_escopo(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])
            _, saida = amb.run(["collect", "--host-group", "Servidores Linux", "--resume", "--examples", "0"])
            self.assertNotIn("Retomando a partir de", saida, "escopo diferente não pode reaproveitar IDs")


class TestInterrupcao(unittest.TestCase):
    def test_falha_no_meio_grava_snapshot_parcial(self):
        """Uma coleta longa que morre na última fase não pode voltar de mãos vazias."""
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeZabbix()

            def cai_nos_itens(payload, headers):
                if payload["method"] == "item.get":
                    raise RuntimeError("conexão derrubada no meio da coleta")
                return fake(payload, headers)

            amb = _Ambiente(tmp, transport=cai_nos_itens)
            with self.assertRaises(RuntimeError):
                amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])

            parciais = [d for d in amb.snapshots if "parcial" in d.name]
            self.assertEqual(len(parciais), 1, "o que já tinha sido coletado precisa ser preservado")

            bruto = json.loads((parciais[0] / "raw" / "zabbix_raw.json").read_text(encoding="utf-8"))
            self.assertTrue(bruto["meta"]["collection"]["partial"])
            self.assertTrue(bruto["data"]["triggers"], "os triggers já coletados continuam no parcial")
            self.assertEqual(bruto["data"]["items"], [], "a fase que não rodou fica vazia, não inventada")
            self.assertTrue(bruto["meta"]["discovered_trigger_ids"], "os IDs ficam gravados para o --resume")

    def test_coleta_interrompida_preserva_o_snapshot_anterior(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            amb.run(["collect", "--host-group", "SIEM", "--examples", "0"])
            bons = [d.name for d in amb.snapshots]

            fake = FakeZabbix()

            def explode(payload, headers):
                if payload["method"] == "hostgroup.get" and (payload.get("params") or {}).get("filter"):
                    raise ZabbixTransientError("HTTP 500: servidor caiu", status=500)
                return fake(payload, headers)

            amb.transport = explode
            codigo, _ = amb.run(["collect", "--host-group", "Servidores Linux", "--examples", "0"])

            self.assertEqual(codigo, cli.EXIT_ZABBIX, "a falha precisa aparecer no código de saída")
            for nome in bons:
                caminho = Path(tmp) / "snapshots" / nome / "raw" / "zabbix_raw.json"
                self.assertTrue(caminho.is_file(), "a coleta boa anterior foi destruída")


class TestReadOnlyPreservado(unittest.TestCase):
    """Item 22: a proteção read-only continua valendo depois da Fase 2."""

    def test_nenhuma_escrita_e_chamada_em_nenhum_comando(self):
        with tempfile.TemporaryDirectory() as tmp:
            amb = _Ambiente(tmp)
            amb.run(["collect", "--host-group", "SIEM", "--page-size", "1", "--examples", "0"])
            amb.run(["collect", "--host-group", "Servidores Linux", "--examples", "0"])
            amb.run(["merge"])
            amb.run(["check"])

            for metodo in amb.transport.methods_called:
                self.assertTrue(
                    metodo.endswith(".get") or metodo == "apiinfo.version",
                    f"método não-leitura chamado: {metodo}",
                )
                for sufixo in (".create", ".update", ".delete", ".import", ".acknowledge"):
                    self.assertFalse(metodo.endswith(sufixo), metodo)


if __name__ == "__main__":
    unittest.main()
