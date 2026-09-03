"""Garantias de que a integração é somente leitura."""

import re
import unittest
from pathlib import Path

from src.zabbix_client import ALLOWED_METHODS, ReadOnlyViolationError, ZabbixReadOnlyClient

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

METODOS_DE_ESCRITA = [
    "trigger.create",
    "trigger.update",
    "trigger.delete",
    "host.create",
    "host.update",
    "host.delete",
    "item.create",
    "item.update",
    "item.delete",
    "hostgroup.create",
    "template.delete",
    "configuration.import",
    "event.acknowledge",
]


def _client(**kwargs) -> ZabbixReadOnlyClient:
    return ZabbixReadOnlyClient(
        "https://zabbix.local", transport=lambda payload, headers: {"result": []}, **kwargs
    )


class TestAllowlist(unittest.TestCase):
    def test_allowlist_so_tem_metodos_de_leitura(self):
        for method in ALLOWED_METHODS:
            self.assertTrue(
                method.endswith(".get") or method == "apiinfo.version",
                f"{method} não é um método de leitura",
            )

    def test_metodos_de_escrita_sao_bloqueados(self):
        client = _client(api_token="t")
        for method in METODOS_DE_ESCRITA:
            with self.assertRaises(ReadOnlyViolationError, msg=method):
                client.call(method, {})

    def test_metodo_desconhecido_e_bloqueado(self):
        with self.assertRaises(ReadOnlyViolationError):
            _client(api_token="t").call("script.execute", {})

    def test_user_login_bloqueado_quando_ha_api_token(self):
        with self.assertRaises(ReadOnlyViolationError):
            _client(api_token="t").call("user.login", {})

    def test_user_login_liberado_apenas_no_fallback_de_senha(self):
        client = _client(user="ro", password="x")
        client.call("user.login", {"username": "ro", "password": "x"}, authenticated=False)

    def test_codigo_fonte_nao_contem_metodos_de_escrita(self):
        padrao = re.compile(
            r"\b(trigger|host|hostgroup|item|template|action|maintenance|script|configuration)"
            r"\.(create|update|delete|massadd|massupdate|massremove|import|execute)\b"
        )
        for arquivo in SRC_DIR.rglob("*.py"):
            encontrados = padrao.findall(arquivo.read_text(encoding="utf-8"))
            self.assertEqual(encontrados, [], f"{arquivo} referencia método de escrita: {encontrados}")


class TestSanitizacaoDeLog(unittest.TestCase):
    def test_credenciais_nunca_vao_para_o_log_de_chamadas(self):
        client = _client(user="ro", password="segredo")
        client.call("user.login", {"username": "ro", "password": "segredo"}, authenticated=False)
        registro = client.call_log[-1]
        self.assertEqual(registro["params"]["password"], "***")
        self.assertNotIn("segredo", str(registro))


if __name__ == "__main__":
    unittest.main()
