"""ETAPA 10: a página gerada a partir das fichas validadas.

O que estes testes protegem, em ordem de gravidade:

1. rascunho não vaza para a página — numa tela de plantão, texto que parece
   procedimento é lido como procedimento;
2. procedimento idêntico não vira N entradas repetidas;
3. a saída é determinística, senão não dá para versionar nem ver diff;
4. o conteúdo não quebra a tabela do Markdown.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.clients import NAO_CLASSIFICADO, ClientRegistry
from src.core.models import LEVEL_FAMILY, SCOPE_MANUAL, AlertDoc, empty_operational
from src.core.repository import AlertRepository
from src.wiki import COLUNAS, SECAO_MANUAL, coletar_entradas, gerar_wiki


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


#: Mapa próprio, para os testes não dependerem do `clients.json` do projeto —
#: que é configuração viva e vai mudar conforme os clientes mudarem.
CLIENTES = {
    "clients": [
        {"id": "chubb", "label": "Chubb", "host_patterns": ["Chubb*"]},
        {"id": "outro-noc", "label": "Outro NOC", "monitored_by_us": False,
         "host_patterns": ["Terceiro*"]},
        {"id": "vibe", "label": "Vibe Tecnologia",
         "host_patterns": ["srv-*", "Vibe*"], "host_groups": ["Vibe Tecnologia"]},
    ]
}


class BaseWiki(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        raiz = Path(self._tmp.name)
        self.docs = raiz / "alerts"
        self.docs.mkdir()
        self.clientes = raiz / "clients.json"
        self.clientes.write_text(json.dumps(CLIENTES), encoding="utf-8")
        self.repo = AlertRepository(self.docs)

    def tearDown(self):
        self._tmp.cleanup()

    def gravar(self, chave, op, zbx=None, scope="zabbix"):
        self.repo.save(AlertDoc(
            alert_key=chave, scope=scope, doc_level=LEVEL_FAMILY, family_key=chave,
            zabbix=zbx, operational=op))

    def pagina(self, **kwargs):
        return gerar_wiki(self.docs, clients_file=self.clientes, **kwargs)

    def entradas(self):
        return coletar_entradas(self.docs, ClientRegistry.load(self.clientes))


class TestSoEntraOQueFoiValidado(BaseWiki):
    def test_rascunho_nao_entra_na_pagina(self):
        """O caso mais grave: rascunho lido como procedimento oficial às 3h."""
        self.gravar("a", operacional(title="Validado"), zabbix())
        self.gravar("b", operacional(title="Rascunho perigoso", doc_status="pending_review"), zabbix())

        pagina = self.pagina()
        self.assertIn("Validado", pagina)
        self.assertNotIn("Rascunho perigoso", pagina)

    def test_undocumented_nao_entra(self):
        self.gravar("a", operacional(title="Nao escrito", doc_status="undocumented"), zabbix())
        self.assertNotIn("Nao escrito", self.pagina())

    def test_reviewed_entra(self):
        self.gravar("a", operacional(title="Revisado", doc_status="reviewed"), zabbix())
        self.assertIn("Revisado", self.pagina())

    def test_pagina_sem_ficha_validada_avisa_em_vez_de_mentir(self):
        self.gravar("a", operacional(doc_status="pending_review"), zabbix())
        pagina = self.pagina()
        self.assertIn("Nenhuma ficha validada", pagina)


class TestAgrupamento(BaseWiki):
    def test_procedimento_identico_vira_uma_entrada(self):
        """Oito famílias de endpoint ENEL receberam o mesmo procedimento. Na
        página viravam oito entradas idênticas, que o operador lê como oito
        casos diferentes."""
        for i in range(3):
            self.gravar(f"enel-{i}", operacional(title="API ENEL indisponível"),
                        zabbix(descricao=f"ENEL API {i} Indisponível", item="services.x[Bearer]"))

        entradas = self.entradas()
        self.assertEqual(len(entradas), 1)
        self.assertEqual(len(entradas[0].alertas), 3)

        pagina = self.pagina()
        self.assertIn("Cobre 3 alertas", pagina)
        self.assertIn("ENEL API 0 Indisponível", pagina)

    def test_procedimentos_diferentes_nao_se_fundem(self):
        self.gravar("a", operacional(title="Disco", actions=["Liberar espaço"]), zabbix())
        self.gravar("b", operacional(title="Rede", actions=["Trocar cabo"]),
                    zabbix(descricao="Link down", item="net.if.in[eth0]"))
        self.assertEqual(len(self.entradas()), 2)

    def test_titulo_diferente_com_mesmo_procedimento_ainda_agrupa(self):
        """O título não faz parte da identidade do procedimento — só o conteúdo."""
        self.gravar("a", operacional(title="Toner preto"), zabbix(descricao="Toner Preto"))
        self.gravar("b", operacional(title="Toner ciano"), zabbix(descricao="Toner Ciano"))
        self.assertEqual(len(self.entradas()), 1)


class TestAlertasManuais(BaseWiki):
    def test_ficam_em_secao_propria(self):
        """Quem lê precisa saber que o Zabbix não avisa desse aqui."""
        self.gravar("manual|rh", operacional(title="RH Cloud — PagamentoNegativo"),
                    None, scope=SCOPE_MANUAL)
        entradas = self.entradas()
        self.assertEqual(entradas[0].categoria, SECAO_MANUAL)
        self.assertTrue(entradas[0].manual)

        pagina = self.pagina()
        self.assertIn(SECAO_MANUAL, pagina)
        self.assertIn("não vêm do Zabbix", pagina)

    def test_ficha_sem_bloco_zabbix_nao_quebra(self):
        self.gravar("manual|x", operacional(title="Sem trigger"), None, scope=SCOPE_MANUAL)
        self.assertIn("Sem trigger", self.pagina())


class TestFormato(BaseWiki):
    def test_saida_e_deterministica(self):
        """Sem isto não dá para versionar o .md nem ver o que mudou num diff."""
        self.gravar("a", operacional(), zabbix())
        self.gravar("b", operacional(title="Outro", actions=["Outra ação"]),
                    zabbix(descricao="Link down", item="net.if.in[eth0]"))
        carimbo = "2026-09-06T00:00:00Z"
        self.assertEqual(self.pagina(gerado_em=carimbo),
                         self.pagina(gerado_em=carimbo))

    def test_pipe_no_conteudo_nao_quebra_a_tabela(self):
        """Descrição de trigger com `|` fecharia a célula no meio."""
        self.gravar("a", operacional(title="Interface Gi0/0 | LAN | uplink"), zabbix())
        pagina = self.pagina()
        self.assertIn(r"Interface Gi0/0 \| LAN \| uplink", pagina)

    def test_quebra_de_linha_no_conteudo_nao_quebra_a_tabela(self):
        self.gravar("a", operacional(meaning="linha um\nlinha dois"), zabbix())
        for linha in self.pagina().splitlines():
            if linha.startswith("|") and "linha um" in linha:
                self.assertIn("linha um linha dois", linha)
                break
        else:
            self.fail("a linha da tabela sumiu")

    def test_usa_o_dialeto_do_wikijs(self):
        self.gravar("a", operacional(), zabbix())
        pagina = self.pagina()
        for marcador in ("{.is-warning}", "{.is-info}", "{.tabset}", "```mermaid"):
            self.assertIn(marcador, pagina, f"faltou {marcador}")

    def test_severidade_vira_icone(self):
        self.gravar("a", operacional(), zabbix(severidade="Disaster"))
        self.assertIn("🔴", self.pagina())

    def test_entrada_com_varios_alertas_mostra_a_severidade_mais_grave(self):
        self.gravar("a", operacional(), zabbix(descricao="Aviso", severidade="Warning"))
        self.gravar("b", operacional(), zabbix(descricao="Grave", severidade="Disaster"))
        entradas = self.entradas()
        self.assertEqual(len(entradas), 1, "mesmo procedimento, uma entrada")
        self.assertEqual(entradas[0].severidade, "Disaster")


class TestOrganizacaoPorCliente(BaseWiki):
    """A wiki abre por cliente, não por categoria técnica.

    O Master Support atende vários clientes: o mesmo "disco cheio" tem
    contato, fila e SLA diferentes conforme o dono do host.
    """

    def test_cada_cliente_vira_uma_secao(self):
        self.gravar("a", operacional(title="Disco Vibe"), zabbix(host="Vibe - Zabbix server"))
        self.gravar("b", operacional(title="Disco Chubb", actions=["Outra ação"]),
                    zabbix(host="Chubb - SQLDB"))

        pagina = self.pagina()
        self.assertIn("### Vibe Tecnologia", pagina)
        self.assertIn("### Chubb", pagina)
        self.assertIn("{.tabset}", pagina)

    def test_mesmo_procedimento_em_clientes_diferentes_nao_se_funde(self):
        """Texto técnico igual, donos diferentes: o contato é de quem é o host."""
        self.gravar("a", operacional(), zabbix(host="Vibe - Zabbix server"))
        self.gravar("b", operacional(), zabbix(host="Chubb - SQLDB"))

        entradas = self.entradas()
        self.assertEqual(len(entradas), 2, "não pode fundir clientes diferentes")
        self.assertEqual({e.cliente for e in entradas}, {"vibe", "chubb"})

    def test_cliente_de_outro_noc_fica_de_fora(self):
        """Procedimento que não é nosso só atrapalha quem está de plantão."""
        self.gravar("a", operacional(title="Nosso"), zabbix(host="Vibe - Zabbix server"))
        self.gravar("b", operacional(title="Do outro NOC", actions=["Não é conosco"]),
                    zabbix(host="Terceiro - Servidor"))

        pagina = self.pagina()
        self.assertIn("Nosso", pagina)
        self.assertNotIn("Do outro NOC", pagina)
        self.assertIn("atendidos por outro NOC", pagina, "quem ficou de fora precisa ser dito")

    def test_indice_de_clientes_no_topo(self):
        self.gravar("a", operacional(), zabbix(host="Vibe - Zabbix server"))
        pagina = self.pagina()
        self.assertIn("## 🏢 Clientes", pagina)
        self.assertIn("| Cliente | Procedimentos | Alertas | Hosts |", pagina)

    def test_ficha_manual_sem_cliente_fica_visivel_como_nao_classificada(self):
        """Chutar o dono mandaria o operador acionar quem não tem a ver."""
        self.gravar("manual|x", operacional(title="MSMonitor STALL"), None, scope=SCOPE_MANUAL)
        entradas = self.entradas()
        self.assertEqual(entradas[0].cliente, NAO_CLASSIFICADO)

        pagina = self.pagina()
        self.assertIn("Não classificado", pagina)
        self.assertIn("clients.json", pagina, "a página precisa dizer como resolver")

    def test_ficha_pode_declarar_o_cliente(self):
        """Saída para o que não tem host: a ficha declara o dono."""
        self.gravar("manual|x", operacional(title="MSMonitor STALL", client="vibe"),
                    None, scope=SCOPE_MANUAL)
        self.assertEqual(self.entradas()[0].cliente, "vibe")

    def test_cliente_declarado_vence_o_host(self):
        """Exceção explícita: host da Vibe, mas o alerta é de outro dono."""
        self.gravar("a", operacional(client="chubb"), zabbix(host="Vibe - Zabbix server"))
        self.assertEqual(self.entradas()[0].cliente, "chubb")


class TestCatalogo(BaseWiki):
    """A tabela larga, no formato que o NOC já usa na wiki de vocês."""

    def test_tem_as_dez_colunas_na_ordem(self):
        self.gravar("a", operacional(), zabbix())
        cabecalho = "| " + " | ".join(COLUNAS) + " |"
        self.assertIn(cabecalho, self.pagina())

    def test_quem_acionar_e_canal_ficam_em_colunas_separadas(self):
        """São perguntas diferentes: quem resolve, e por onde falar com ele."""
        op = operacional()
        op["routing"] = {**op["routing"], "team": "Infraestrutura", "ticket_queue": "DeskManager"}
        op["escalation"] = {**op["escalation"], "to": "Rafael Sales", "channel": "Teams"}
        self.gravar("a", op, zabbix())

        linha = next(l for l in self.pagina().splitlines() if l.startswith("| `Disco cheio`"))
        celulas = [c.strip() for c in linha.strip("|").split("|")]
        self.assertEqual(celulas[6], "Infraestrutura", "coluna 'Quem Acionar' é só o time")
        self.assertIn("DeskManager", celulas[7])
        self.assertIn("(Rafael Sales)", celulas[7], "o contato vem colado no canal")

    def test_severidade_no_vocabulario_do_plantao(self):
        """`Disaster` não diz nada sobre postura; `Crítica` diz."""
        self.gravar("a", operacional(), zabbix(severidade="Disaster"))
        self.assertIn("🔴 Crítica", self.pagina())
        self.assertNotIn("| Disaster |", self.pagina())

    def test_wrapper_de_rolagem(self):
        """Dez colunas não cabem na largura da página; sem o min-width o
        navegador espreme a coluna de ação até virar ilegível."""
        self.gravar("a", operacional(), zabbix())
        pagina = self.pagina()
        self.assertIn('overflow-x: auto', pagina)
        self.assertIn('min-width: 1800px', pagina)

    def test_referencia_sai_das_notas_e_nao_e_inventada(self):
        self.gravar("a", operacional(notes="Ver https://wiki.exemplo/status"), zabbix())
        self.assertIn("[link](https://wiki.exemplo/status)", self.pagina())

        self.gravar("b", operacional(title="Outro", actions=["X"], notes="Ref: 0726-001673"),
                    zabbix(descricao="Outro alerta"))
        self.assertIn("Ref: 0726-001673", self.pagina())

    def test_sem_referencia_mostra_travessao(self):
        """Ausência é informação: ninguém anexou link nem chamado ainda."""
        self.gravar("a", operacional(notes=""), zabbix())
        linha = next(l for l in self.pagina().splitlines() if l.startswith("| `Disco cheio`"))
        self.assertTrue(linha.rstrip().endswith("| — |"))


class TestMatrizDeAcionamento(BaseWiki):
    def test_e_derivada_das_fichas(self):
        """Escrita à mão, a matriz descola das fichas com o tempo."""
        self.gravar("a", operacional(), zabbix())
        op_soc = operacional(title="Incidente")
        op_soc["routing"] = {**op_soc["routing"], "team": "SOC", "ticket_queue": "fila SOC"}
        self.gravar("b", op_soc, zabbix(descricao="Incidente", item="onesecure.incident"))

        pagina = self.pagina()
        self.assertIn("**Infraestrutura**", pagina)
        self.assertIn("**SOC**", pagina)
        self.assertIn("fila SOC", pagina)

    def test_ficha_sem_time_nao_inventa_um(self):
        op = operacional()
        op["routing"] = {**op["routing"], "team": ""}
        self.gravar("a", op, zabbix())
        pagina = self.pagina()
        self.assertNotIn("| **| ", pagina)


if __name__ == "__main__":
    unittest.main()
