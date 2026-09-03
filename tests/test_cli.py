"""CLI: `python main.py collect` de ponta a ponta, com o Zabbix falso."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from src import cli
from src.config import Settings
from src.zabbix_client import ZabbixReadOnlyClient
from tests.fixtures.fake_zabbix import FakeZabbix


def _fake_client(settings, transport=None):
    return ZabbixReadOnlyClient(settings.url, api_token=settings.api_token, transport=FakeZabbix())


class TestCliCollect(unittest.TestCase):
    def test_collect_gera_snapshot_e_relatorio(self):
        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(url="https://zabbix.local", api_token="fake-token", output_dir=tmp)
            buffer = io.StringIO()
            with mock.patch.object(cli, "load_settings", return_value=settings), mock.patch.object(
                ZabbixReadOnlyClient, "from_settings", staticmethod(_fake_client)
            ), redirect_stdout(buffer):
                codigo = cli.main(["collect", "--examples", "1"])

            self.assertEqual(codigo, cli.EXIT_OK)
            saida = buffer.getvalue()
            self.assertIn("✓ 6 triggers encontrados", saida)
            self.assertIn("✓ 4 alertas únicos", saida)
            self.assertIn("Exemplos de alertas normalizados", saida)

            snapshots = sorted((Path(tmp) / "snapshots").glob("2*"))
            self.assertEqual(len(snapshots), 1)
            relatorio = json.loads((snapshots[0] / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(relatorio["counts"]["triggers"], 6)
            self.assertEqual(relatorio["normalization"]["unique_alert_keys"], 4)
            self.assertEqual(len(relatorio["collisions"]), 1)

    def test_erro_de_configuracao_tem_codigo_de_saida_proprio(self):
        with tempfile.TemporaryDirectory() as tmp:
            vazio = Path(tmp) / "sem.env"
            vazio.write_text("", encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    codigo = cli.main(["--env-file", str(vazio), "collect"])
            self.assertEqual(codigo, cli.EXIT_CONFIG)


if __name__ == "__main__":
    unittest.main()
