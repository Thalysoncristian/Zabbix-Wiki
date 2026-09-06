"""ETAPA 10: a página gerada a partir das fichas validadas.

O que estes testes protegem, em ordem de gravidade:

1. rascunho não vaza para a página — numa tela de plantão, texto que parece
   procedimento é lido como procedimento;
2. procedimento idêntico não vira N entradas repetidas;
3. a saída é determinística, senão não dá para versionar nem ver diff;
4. o conteúdo não quebra a tabela do Markdown.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.core.models import LEVEL_FAMILY, SCOPE_MANUAL, AlertDoc, empty_operational
from src.core.repository import AlertRepository
from src.wiki import SECAO_MANUAL, coletar_entradas, gerar_wiki


def operacional(**campos):
    base = empty_operational()
    base.update({
        "doc_status": "documented",
        "title": "Disco cheio",
        "meaning": "A partição raiz encheu.",
        "probable_cause": "Log crescendo.",
        "actions": ["Liberar espaço"],
        "requires_ticket": True,
        "resolution_criteria": "Uso volta ao normal.",
    })
    base["routing"] = {**base["routing"], "team": "Infraestrutura", "ticket_queue": "DeskManager"}
    base.update(campos)
    return base


def zabbix(descricao="/: Disk space is low", host="srv-01", severidade="Warning", item="vfs.fs.size[/,pused]"):
    return {
        "triggerid": "1",
        "description_raw": descricao,
        "priority": {"value": "2", "name": severidade},
        "host": {"hostid": "10", "host": host, "name": host},
        "host_groups": ["Vibe Tecnologia"],
        "items": [{"itemid": "5", "key_": item, "name": item}],
    }


class BaseWiki(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.docs = Path(self._tmp.name)
        self.repo = AlertRepository(self.docs)

    def tearDown(self):
        self._tmp.cleanup()

    def gravar(self, chave, op, zbx=None, scope="zabbix"):
        self.repo.save(AlertDoc(
            alert_key=chave, scope=scope, doc_level=LEVEL_FAMILY, family_key=chave,
            zabbix=zbx, operational=op))


class TestSoEntraOQueFoiValidado(BaseWiki):
    def test_rascunho_nao_entra_na_pagina(self):
        """O caso mais grave: rascunho lido como procedimento oficial às 3h."""
        self.gravar("a", operacional(title="Validado"), zabbix())
        self.gravar("b", operacional(title="Rascunho perigoso", doc_status="pending_review"), zabbix())

        pagina = gerar_wiki(self.docs)
        self.assertIn("Validado", pagina)
        self.assertNotIn("Rascunho perigoso", pagina)

    def test_undocumented_nao_entra(self):
        self.gravar("a", operacional(title="Nao escrito", doc_status="undocumented"), zabbix())
        self.assertNotIn("Nao escrito", gerar_wiki(self.docs))

    def test_reviewed_entra(self):
        self.gravar("a", operacional(title="Revisado", doc_status="reviewed"), zabbix())
        self.assertIn("Revisado", gerar_wiki(self.docs))

    def test_pagina_sem_ficha_validada_avisa_em_vez_de_mentir(self):
        self.gravar("a", operacional(doc_status="pending_review"), zabbix())
        pagina = gerar_wiki(self.docs)
        self.assertIn("Nenhuma ficha validada", pagina)


class TestAgrupamento(BaseWiki):
    def test_procedimento_identico_vira_uma_entrada(self):
        """Oito famílias de endpoint ENEL receberam o mesmo procedimento. Na
        página viravam oito entradas idênticas, que o operador lê como oito
        casos diferentes."""
        for i in range(3):
            self.gravar(f"enel-{i}", operacional(title="API ENEL indisponível"),
                        zabbix(descricao=f"ENEL API {i} Indisponível", item="services.x[Bearer]"))

        entradas = coletar_entradas(self.docs)
        self.assertEqual(len(entradas), 1)
        self.assertEqual(len(entradas[0].alertas), 3)

        pagina = gerar_wiki(self.docs)
        self.assertIn("Cobre 3 alertas", pagina)
        self.assertIn("ENEL API 0 Indisponível", pagina)

    def test_procedimentos_diferentes_nao_se_fundem(self):
        self.gravar("a", operacional(title="Disco", actions=["Liberar espaço"]), zabbix())
        self.gravar("b", operacional(title="Rede", actions=["Trocar cabo"]),
                    zabbix(descricao="Link down", item="net.if.in[eth0]"))
        self.assertEqual(len(coletar_entradas(self.docs)), 2)

    def test_titulo_diferente_com_mesmo_procedimento_ainda_agrupa(self):
        """O título não faz parte da identidade do procedimento — só o conteúdo."""
        self.gravar("a", operacional(title="Toner preto"), zabbix(descricao="Toner Preto"))
        self.gravar("b", operacional(title="Toner ciano"), zabbix(descricao="Toner Ciano"))
        self.assertEqual(len(coletar_entradas(self.docs)), 1)


class TestAlertasManuais(BaseWiki):
    def test_ficam_em_secao_propria(self):
        """Quem lê precisa saber que o Zabbix não avisa desse aqui."""
        self.gravar("manual|rh", operacional(title="RH Cloud — PagamentoNegativo"),
                    None, scope=SCOPE_MANUAL)
        entradas = coletar_entradas(self.docs)
        self.assertEqual(entradas[0].categoria, SECAO_MANUAL)
        self.assertTrue(entradas[0].manual)

        pagina = gerar_wiki(self.docs)
        self.assertIn(SECAO_MANUAL, pagina)
        self.assertIn("não vêm do Zabbix", pagina)

    def test_ficha_sem_bloco_zabbix_nao_quebra(self):
        self.gravar("manual|x", operacional(title="Sem trigger"), None, scope=SCOPE_MANUAL)
        self.assertIn("Sem trigger", gerar_wiki(self.docs))


class TestFormato(BaseWiki):
    def test_saida_e_deterministica(self):
        """Sem isto não dá para versionar o .md nem ver o que mudou num diff."""
        self.gravar("a", operacional(), zabbix())
        self.gravar("b", operacional(title="Outro", actions=["Outra ação"]),
                    zabbix(descricao="Link down", item="net.if.in[eth0]"))
        carimbo = "2026-09-06T00:00:00Z"
        self.assertEqual(gerar_wiki(self.docs, gerado_em=carimbo),
                         gerar_wiki(self.docs, gerado_em=carimbo))

    def test_pipe_no_conteudo_nao_quebra_a_tabela(self):
        """Descrição de trigger com `|` fecharia a célula no meio."""
        self.gravar("a", operacional(title="Interface Gi0/0 | LAN | uplink"), zabbix())
        pagina = gerar_wiki(self.docs)
        self.assertIn(r"Interface Gi0/0 \| LAN \| uplink", pagina)

    def test_quebra_de_linha_no_conteudo_nao_quebra_a_tabela(self):
        self.gravar("a", operacional(meaning="linha um\nlinha dois"), zabbix())
        for linha in gerar_wiki(self.docs).splitlines():
            if linha.startswith("|") and "linha um" in linha:
                self.assertIn("linha um linha dois", linha)
                break
        else:
            self.fail("a linha da tabela sumiu")

    def test_usa_o_dialeto_do_wikijs(self):
        self.gravar("a", operacional(), zabbix())
        pagina = gerar_wiki(self.docs)
        for marcador in ("{.is-warning}", "{.is-info}", "{.tabset}", "<details>", "```mermaid"):
            self.assertIn(marcador, pagina, f"faltou {marcador}")

    def test_severidade_vira_icone(self):
        self.gravar("a", operacional(), zabbix(severidade="Disaster"))
        self.assertIn("🔴", gerar_wiki(self.docs))

    def test_entrada_com_varios_alertas_mostra_a_severidade_mais_grave(self):
        self.gravar("a", operacional(), zabbix(descricao="Aviso", severidade="Warning"))
        self.gravar("b", operacional(), zabbix(descricao="Grave", severidade="Disaster"))
        entradas = coletar_entradas(self.docs)
        self.assertEqual(len(entradas), 1, "mesmo procedimento, uma entrada")
        self.assertEqual(entradas[0].severidade, "Disaster")


class TestMatrizDeAcionamento(BaseWiki):
    def test_e_derivada_das_fichas(self):
        """Escrita à mão, a matriz descola das fichas com o tempo."""
        self.gravar("a", operacional(), zabbix())
        op_soc = operacional(title="Incidente")
        op_soc["routing"] = {**op_soc["routing"], "team": "SOC", "ticket_queue": "fila SOC"}
        self.gravar("b", op_soc, zabbix(descricao="Incidente", item="onesecure.incident"))

        pagina = gerar_wiki(self.docs)
        self.assertIn("**Infraestrutura**", pagina)
        self.assertIn("**SOC**", pagina)
        self.assertIn("fila SOC", pagina)

    def test_ficha_sem_time_nao_inventa_um(self):
        op = operacional()
        op["routing"] = {**op["routing"], "team": ""}
        self.gravar("a", op, zabbix())
        pagina = gerar_wiki(self.docs)
        self.assertNotIn("| **| ", pagina)


if __name__ == "__main__":
    unittest.main()
