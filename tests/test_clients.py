"""De quem é cada alerta — o mapa host -> cliente.

O Master Support atende vários clientes, e atribuir um alerta ao cliente
errado é pior que não atribuir: manda o operador acionar quem não tem nada a
ver com aquilo, de madrugada.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.clients import NAO_CLASSIFICADO, ClientRegistry

#: Reproduz o formato real, incluindo o caso ambíguo que motivou a ordem:
#: "Vibe Crédito Banpará" é host do Banpará, não da Vibe.
CONFIG = {
    "clients": [
        {"id": "banpara", "label": "Banpará", "monitored_by_us": False,
         "host_patterns": ["Vibe Crédito Banpará*", "Banpara*"]},
        {"id": "chubb", "label": "Chubb",
         "hosts": ["Control-M server [IN01]"], "host_patterns": ["Chubb*"]},
        {"id": "master-support", "label": "Master Support",
         "hosts": ["ONESecure"], "host_groups": ["Master Support"]},
        {"id": "vibe", "label": "Vibe Tecnologia",
         "host_patterns": ["Vibe*"], "host_groups": ["Vibe Tecnologia", "Zabbix servers"]},
    ]
}


class BaseClientes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.arquivo = Path(self._tmp.name) / "clients.json"
        self.arquivo.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.reg = ClientRegistry.load(self.arquivo)

    def tearDown(self):
        self._tmp.cleanup()


class TestResolucao(BaseClientes):
    def test_prefixo_do_host_decide(self):
        self.assertEqual(self.reg.resolve("Chubb - SQLDB"), "chubb")
        self.assertEqual(self.reg.resolve("Vibe - Zabbix server"), "vibe")

    def test_nome_exato_vence_para_host_sem_prefixo(self):
        """`Control-M server [IN01]` não diz de quem é pelo nome."""
        self.assertEqual(self.reg.resolve("Control-M server [IN01]"), "chubb")

    def test_ordem_resolve_o_nome_ambiguo(self):
        """O caso que motivou a ordem do arquivo: começa com 'Vibe' e é do
        Banpará. Errar aqui aciona o cliente errado no meio da madrugada."""
        self.assertEqual(self.reg.resolve("Vibe Crédito Banpará (máquinas)"), "banpara")

    def test_host_group_e_o_ultimo_recurso(self):
        """Host sem prefixo de cliente, mas dentro de um grupo conhecido."""
        self.assertEqual(self.reg.resolve("SRV_INCONTROL_2026", groups=("Vibe Tecnologia",)), "vibe")

    def test_prefixo_vence_o_host_group(self):
        """O grupo é técnico e mistura clientes; o nome é mais específico."""
        self.assertEqual(
            self.reg.resolve("Chubb - Links de API", groups=("Vibe Tecnologia",)), "chubb")

    def test_sem_match_nao_chuta(self):
        """Atribuir por palpite é pior que assumir que não se sabe."""
        self.assertEqual(self.reg.resolve("maquina-misteriosa"), NAO_CLASSIFICADO)

    def test_nao_diferencia_maiusculas(self):
        self.assertEqual(self.reg.resolve("chubb - sqldb"), "chubb")

    def test_usa_o_nome_tecnico_quando_o_visivel_nao_casa(self):
        self.assertEqual(self.reg.resolve("host-sem-padrao", "Chubb - API"), "chubb")


class TestAlertaCompleto(BaseClientes):
    def test_resolve_a_partir_do_alerta_normalizado(self):
        alerta = {"zabbix": {"host": {"name": "Chubb - SQLDB", "host": "chubb-sqldb"},
                             "host_groups": ["Cliente_chubb"]}}
        self.assertEqual(self.reg.resolve_alert(alerta), "chubb")

    def test_alerta_sem_host_nao_quebra(self):
        self.assertEqual(self.reg.resolve_alert({"zabbix": {}}), NAO_CLASSIFICADO)


class TestAtendimento(BaseClientes):
    def test_cliente_de_outro_noc_e_marcado(self):
        self.assertFalse(self.reg.is_monitored("banpara"))
        self.assertTrue(self.reg.is_monitored("chubb"))

    def test_nao_classificado_conta_como_nosso(self):
        """Esconder o que não se sabe seria decidir por omissão."""
        self.assertTrue(self.reg.is_monitored(NAO_CLASSIFICADO))

    def test_rotulo_legivel(self):
        self.assertEqual(self.reg.label_of("banpara"), "Banpará")
        self.assertEqual(self.reg.label_of(NAO_CLASSIFICADO), "Não classificado")


class TestArquivo(unittest.TestCase):
    def test_sem_arquivo_nada_e_classificado(self):
        """Ausência de configuração não pode virar palpite."""
        with tempfile.TemporaryDirectory() as tmp:
            reg = ClientRegistry.load(Path(tmp) / "nao-existe.json")
            self.assertEqual(reg.resolve("Chubb - SQLDB"), NAO_CLASSIFICADO)

    def test_json_invalido_falha_alto(self):
        """Melhor quebrar do que classificar tudo errado em silêncio."""
        with tempfile.TemporaryDirectory() as tmp:
            ruim = Path(tmp) / "clients.json"
            ruim.write_text("{ isto não é json", encoding="utf-8")
            with self.assertRaises(ValueError):
                ClientRegistry.load(ruim)

    def test_cliente_sem_id_e_ignorado(self):
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "clients.json"
            arquivo.write_text(json.dumps({"clients": [{"label": "sem id"}]}), encoding="utf-8")
            self.assertEqual(ClientRegistry.load(arquivo).clients, ())


class TestConfiguracaoReal(unittest.TestCase):
    """O `clients.json` do repositório precisa continuar coerente."""

    def setUp(self):
        self.reg = ClientRegistry.load("clients.json")

    def test_o_arquivo_do_projeto_carrega(self):
        self.assertTrue(self.reg.clients, "clients.json vazio ou ausente")

    def test_os_clientes_citados_existem(self):
        ids = {c.id for c in self.reg.clients}
        for esperado in ("vibe", "chubb", "votorantim", "saq", "master-support"):
            self.assertIn(esperado, ids)

    def test_banpara_vem_antes_da_vibe(self):
        """Se essa ordem inverter, 'Vibe Crédito Banpará' vai para o cliente
        errado — e o teste é o único lugar que percebe."""
        ordem = [c.id for c in self.reg.clients]
        self.assertLess(ordem.index("banpara"), ordem.index("vibe"))
        self.assertEqual(self.reg.resolve("Vibe Crédito Banpará (máquinas)"), "banpara")

    def test_control_m_do_in01_e_da_chubb(self):
        self.assertEqual(self.reg.resolve("Control-M server [IN01]"), "chubb")
        self.assertEqual(self.reg.resolve("Control-M SaaS Master"), "chubb")

    def test_control_m_votorantim_e_do_votorantim(self):
        self.assertEqual(self.reg.resolve("Control-M PRD Votorantim"), "votorantim")


if __name__ == "__main__":
    unittest.main()
