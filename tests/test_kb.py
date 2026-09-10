"""Base de conhecimento do NOC: leitura do wiki, casamento e importação.

O teste que dá nome a este arquivo é o do `STALL`. Num casamento por substring,
o item `STALL` do wiki (coletor do MSMonitor parado) casa com o alerta
`Linux: Number of installed packages has been changed` — "in**stall**ed" contém
"stall" —, e o procedimento de plantão telefônico é anexado a um alerta de
inventário de pacotes. É um erro silencioso e plausível, do tipo que só aparece
às três da manhã. Aqui ele é um teste.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src.collect import collect_raw
from src.core.repository import AlertRepository
from src.kb.apply import merge_operational, missing_from_wiki, operational_from_entry
from src.kb.catalog import CatalogError, parse_catalog, parse_routing, parse_sla
from src.kb.links import LINKED, MANUAL, PENDING, REJECTED, LinkError, LinkStore
from src.kb.matching import palavras, suggest_for_entry
from src.normalize import normalize_snapshot
from src.snapshot import write_snapshot
from src.web.readmodel import ReadModel, kb_doc_key, resolve_snapshot
from src.web.server import serve
from src.zabbix_client import ZabbixReadOnlyClient
from tests.fixtures.fake_zabbix import FakeZabbix

#: Um catálogo mínimo com a mesma forma do wiki real: matriz de acionamento,
#: tabela de ação rápida e tabela de referência técnica.
CATALOGO = """# 📘 Catálogo de Alertas Internos

## ☎️ Matriz de acionamento

| Fila / Time | Responsável por | Canal primário | Escalonamento | Horário |
| :--- | :--- | :--- | :--- | :--- |
| **Infraestrutura** | Disco, rede, servidores | DeskManager | Teams — Rafael Sales | A confirmar |
| **Sobreaviso MSMonitor** | Coletores MSMonitor | Telefone — Jordy | — | Plantão |

## 📋 Catálogo por categoria

### 🖥️ Infraestrutura & Redes

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `/var: Disk space is critically low` | 🔴 | Vibe - Zabbix Proxy | Abrir chamado solicitando liberação de espaço. | Infraestrutura · DeskManager | ⏱️ Imediato |
| `Serviço parado` | 🟡 | Vibe - App Server | Abrir chamado. Sem resposta, acionar no Teams. | Infraestrutura · DeskManager → Teams | ⏱️ 7 min (5m + 2m) |

#### Referência técnica — Infraestrutura & Redes

| Alerta | Descrição | Causa provável | Referência |
| :--- | :--- | :--- | :--- |
| `/var: Disk space is critically low` | Partição /var em nível crítico. | Crescimento de logs. | Ref: 0726-001673 |
| `Serviço parado` | Um serviço do sistema deixou de responder. | Falha do processo. | — |

### 🔗 Monitoramento & Integrações

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `STALL` | 🟠 | MSMonitor | Aguardar a recuperação automática. Se persistir, acionar o plantão. | Sobreaviso MSMonitor · Telefone (Jordy) | ⏱️ Imediato |

#### Referência técnica — Monitoramento & Integrações

| Alerta | Descrição | Causa provável | Referência |
| :--- | :--- | :--- | :--- |
| `STALL` | Nenhum arquivo de alerta recebido em N verificações. | Coletor parado. | — |
"""


def escrever_catalogo(diretorio: Path, texto: str = CATALOGO) -> Path:
    caminho = diretorio / "catalogo.md"
    caminho.write_text(texto, encoding="utf-8")
    return caminho


def montar_snapshot(base: str) -> Path:
    cliente = ZabbixReadOnlyClient("https://zabbix.local", api_token="fake-token", transport=FakeZabbix())
    raw = collect_raw(cliente)
    return write_snapshot(base, raw, normalize_snapshot(raw))["snapshot_dir"]


# --------------------------------------------------------------------- leitura
class TestLeituraDoCatalogo(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalogo = parse_catalog(escrever_catalogo(Path(self._tmp.name)))

    def tearDown(self):
        self._tmp.cleanup()

    def test_le_todas_as_entradas_com_categoria(self):
        self.assertEqual(len(self.catalogo.entries), 3)
        self.assertEqual(self.catalogo.categories,
                         ["Infraestrutura & Redes", "Monitoramento & Integrações"])

    def test_une_tabela_de_acao_e_referencia_tecnica_pelo_nome(self):
        entrada = next(e for e in self.catalogo.entries if e.name.startswith("/var"))
        self.assertEqual(entrada.action, "Abrir chamado solicitando liberação de espaço.")
        self.assertEqual(entrada.description, "Partição /var em nível crítico.")
        self.assertEqual(entrada.probable_cause, "Crescimento de logs.")
        self.assertEqual(entrada.reference, "Ref: 0726-001673")

    def test_severidade_do_wiki_nao_vira_severidade_do_zabbix(self):
        """Escalas diferentes. Transportar o rótulo é honesto; mapear seria inventar."""
        entrada = next(e for e in self.catalogo.entries if e.name.startswith("/var"))
        self.assertEqual(entrada.severity_icon, "🔴")
        self.assertEqual(entrada.severity_label, "Crítico (wiki)")
        self.assertNotIn(entrada.severity_label, ("Disaster", "High", "Average", "Warning"))

    def test_resolve_a_fila_contra_a_matriz_de_acionamento(self):
        entrada = next(e for e in self.catalogo.entries if e.name == "STALL")
        self.assertEqual(entrada.team, "Sobreaviso MSMonitor")
        self.assertIsNotNone(entrada.escalation)
        self.assertEqual(entrada.escalation.schedule, "Plantão")

    def test_traco_na_referencia_vira_vazio_e_nao_o_traco(self):
        entrada = next(e for e in self.catalogo.entries if e.name == "STALL")
        self.assertEqual(entrada.reference, "")

    def test_ids_sao_estaveis_entre_leituras(self):
        outro = parse_catalog(Path(self._tmp.name) / "catalogo.md")
        self.assertEqual([e.id for e in self.catalogo.entries], [e.id for e in outro.entries])

    def test_arquivo_ausente_diz_o_que_fazer(self):
        with self.assertRaises(CatalogError) as ctx:
            parse_catalog(Path(self._tmp.name) / "nao-existe.md")
        self.assertIn("Cole a versão atual do wiki", str(ctx.exception))


class TestPrazoEFila(unittest.TestCase):
    def test_imediato_significa_zero_e_nao_desconhecido(self):
        sla = parse_sla("⏱️ Imediato")
        self.assertTrue(sla.immediate)
        self.assertEqual(sla.wait_minutes, 0)
        self.assertIsNone(sla.escalate_after_minutes)

    def test_duas_etapas_viram_espera_e_escalonamento(self):
        sla = parse_sla("⏱️ 7 min (5m + 2m)")
        self.assertEqual(sla.parts, (5, 2))
        self.assertEqual(sla.wait_minutes, 5)
        self.assertEqual(sla.escalate_after_minutes, 7)

    def test_numero_solto_e_espera_sem_escalonamento(self):
        sla = parse_sla("⏱️ 5 min")
        self.assertEqual(sla.wait_minutes, 5)
        self.assertIsNone(sla.escalate_after_minutes)

    def test_celula_vazia_nao_inventa_prazo(self):
        sla = parse_sla("—")
        self.assertIsNone(sla.wait_minutes)

    def test_fila_e_canal_saem_separados(self):
        self.assertEqual(parse_routing("Infraestrutura · DeskManager → Teams"),
                         ("Infraestrutura", "DeskManager → Teams"))
        self.assertEqual(parse_routing("NOC"), ("NOC", ""))


# ------------------------------------------------------------------ casamento
class TestCasamento(unittest.TestCase):
    """O casamento é por palavra inteira — e o `STALL` é o motivo."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.output = cls._tmp.name
        cls.docs = str(Path(cls._tmp.name) / "docs")
        montar_snapshot(cls.output)
        cls.catalogo = parse_catalog(escrever_catalogo(Path(cls._tmp.name)))
        cls.modelo = ReadModel(resolve_snapshot(cls.output), cls.docs, catalog=cls.catalogo,
                               links=LinkStore(Path(cls._tmp.name) / "kb_links.json"))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _sugestoes(self, nome: str) -> list[Any]:
        entrada = next(e for e in self.catalogo.entries if e.name == nome)
        return suggest_for_entry(entrada, self.modelo)

    def test_stall_nao_casa_com_installed(self):
        """O caso que define o módulo: substring casaria, palavra inteira não."""
        self.assertIn("stall", "linux: number of installed packages has been changed")
        for sugestao in self._sugestoes("STALL"):
            self.assertNotIn("installed", sugestao.label.lower(),
                             "casamento por substring voltou: STALL casou com 'installed'")

    def test_nome_identico_casa_com_confianca_alta(self):
        sugestoes = [s for s in self._sugestoes("Serviço parado") if s.kind == "family"]
        self.assertTrue(sugestoes)
        melhor = sugestoes[0]
        self.assertEqual(melhor.confidence, "high")
        self.assertTrue(any("exatamente" in m for m in melhor.reasons))

    def test_lld_casa_pelo_prototipo_e_o_motivo_mostra_o_que_faltou(self):
        """O wiki fala de `/var`; a família é `{#FSNAME}`, a forma da regra.

        O casamento acontece pelas palavras em comum, e o motivo diz quantas
        casaram — quem lê vê que `/var` não está do outro lado.
        """
        sugestoes = [s for s in self._sugestoes("/var: Disk space is critically low")
                     if s.kind == "family"]
        rotulos = [s.label for s in sugestoes]
        self.assertIn("{#FSNAME}: Disk space is critically low", rotulos)
        prototipo = next(s for s in sugestoes if s.label.startswith("{#FSNAME}"))
        self.assertEqual(prototipo.confidence, "medium")
        self.assertTrue(any("4 de 5 palavras" in m for m in prototipo.reasons))

    def test_nome_do_wiki_que_e_so_um_pedaco_do_alerta_nao_e_alta(self):
        """`Disk space is critically low` dentro de um texto bem maior é, no
        máximo, um alerta vizinho — e a confiança precisa dizer isso."""
        sugestoes = [s for s in self._sugestoes("/var: Disk space is critically low")
                     if s.label.startswith("Linux:")]
        self.assertTrue(sugestoes)
        self.assertEqual(sugestoes[0].confidence, "medium")
        self.assertTrue(any("pode ser um alerta relacionado" in m for m in sugestoes[0].reasons))

    def test_todo_casamento_traz_o_motivo_em_texto(self):
        for nome in ("/var: Disk space is critically low", "Serviço parado"):
            for sugestao in self._sugestoes(nome):
                self.assertTrue(sugestao.reasons, f"{nome}: sugestão sem motivo")
                self.assertTrue(all(isinstance(m, str) and m for m in sugestao.reasons))

    def test_host_divergente_vira_aviso_e_nao_silencio(self):
        """O wiki diz `Vibe - App Server`; o alerta está no `Vibe - Wazuh SIEM`.

        O texto casa perfeitamente e o host não. Esconder isso seria oferecer
        uma confirmação de olhos fechados.
        """
        sugestoes = [s for s in self._sugestoes("Serviço parado") if s.kind == "family"]
        motivos = " ".join(m for s in sugestoes for m in s.reasons)
        self.assertIn("o host do wiki é “Vibe - App Server”", motivos)
        self.assertIn("o texto casa, o host não", motivos)

    def test_host_conferindo_aparece_como_motivo(self):
        sugestoes = [s for s in self._sugestoes("/var: Disk space is critically low")
                     if s.kind == "family"]
        motivos = " ".join(m for s in sugestoes for m in s.reasons)
        self.assertIn("confere com o host “Vibe - Zabbix Proxy”", motivos)

    def test_sugestao_de_regra_e_derivada_e_diz_isso(self):
        regras = [s for s in self._sugestoes("Serviço parado") if s.kind == "rule"]
        self.assertTrue(regras)
        for sugestao in regras:
            self.assertTrue(any("faz parte deste agrupamento" in m for m in sugestao.reasons))

    def test_palavras_descarta_conectivos(self):
        self.assertEqual(palavras("Disk space is low"), ["disk", "space", "low"])


# ------------------------------------------------------------------ aplicação
class TestTraducaoParaFicha(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.catalogo = parse_catalog(escrever_catalogo(Path(self._tmp.name)))

    def tearDown(self):
        self._tmp.cleanup()

    def _entrada(self, nome: str):
        return next(e for e in self.catalogo.entries if e.name == nome)

    def test_cada_campo_escrito_declara_a_origem(self):
        bloco, fontes = operational_from_entry(self._entrada("Serviço parado"), self.catalogo)
        self.assertTrue(bloco)
        for campo in bloco:
            self.assertIn(campo, fontes, f"{campo} foi escrito sem dizer de onde veio")
            self.assertTrue(fontes[campo])

    def test_prazo_do_wiki_vira_espera_e_escalonamento(self):
        bloco, _ = operational_from_entry(self._entrada("Serviço parado"), self.catalogo)
        self.assertEqual(bloco["wait_before_ticket_minutes"], 5)
        self.assertEqual(bloco["escalation"]["after_minutes"], 7)
        self.assertEqual(bloco["escalation"]["to"], "Teams — Rafael Sales")

    def test_requires_ticket_e_leitura_do_texto_com_a_frase_junto(self):
        bloco, fontes = operational_from_entry(self._entrada("Serviço parado"), self.catalogo)
        self.assertTrue(bloco["requires_ticket"])
        self.assertIn("Abrir chamado", fontes["requires_ticket"])

    def test_campos_lidos_do_texto_nunca_viram_falso_por_silencio(self):
        """"O wiki não diz" é ausência, não negação.

        `requires_ticket` é campo obrigatório para marcar a ficha como
        documentada: gravar `False` porque a ação não fala em chamado deixaria
        a validação passar com uma resposta que ninguém deu.
        """
        parado, _ = operational_from_entry(self._entrada("Serviço parado"), self.catalogo)
        self.assertNotIn("self_resolves", parado)
        self.assertTrue(parado["requires_ticket"])

        stall, _ = operational_from_entry(self._entrada("STALL"), self.catalogo)
        self.assertTrue(stall["self_resolves"])
        self.assertNotIn("requires_ticket", stall)
        self.assertTrue(any("requires_ticket" in f for f in missing_from_wiki(self._entrada("STALL"))))

    def test_o_wiki_nao_preenche_criterio_de_resolucao(self):
        for entrada in self.catalogo.entries:
            bloco, _ = operational_from_entry(entrada, self.catalogo)
            self.assertNotIn("resolution_criteria", bloco)
            self.assertIn("resolution_criteria (como saber que foi resolvido)",
                          missing_from_wiki(entrada))

    def test_importacao_nao_apaga_texto_ja_escrito(self):
        atual = {"meaning": "O que a equipe escreveu", "actions": [], "routing": {"team": "SOC"}}
        novo = {"meaning": "O que o wiki diz", "actions": ["Abrir chamado"],
                "routing": {"team": "Infraestrutura", "channel": "DeskManager"}}
        fundido, escritos, preservados = merge_operational(atual, novo)
        self.assertEqual(fundido["meaning"], "O que a equipe escreveu")
        self.assertIn("meaning", preservados)
        self.assertEqual(fundido["actions"], ["Abrir chamado"])
        self.assertIn("actions", escritos)
        # Campo composto: o canal entra sem derrubar a equipe já definida.
        self.assertEqual(fundido["routing"]["team"], "SOC")
        self.assertEqual(fundido["routing"]["channel"], "DeskManager")
        self.assertIn("routing.team", preservados)

    def test_overwrite_e_explicito(self):
        atual = {"meaning": "antigo"}
        fundido, escritos, _ = merge_operational(atual, {"meaning": "novo"}, overwrite=True)
        self.assertEqual(fundido["meaning"], "novo")
        self.assertIn("meaning", escritos)


# --------------------------------------------------------------------- estado
class TestLinkStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = LinkStore(Path(self._tmp.name) / "kb_links.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_item_nao_avaliado_nasce_pendente(self):
        self.assertEqual(self.store.get("x")["status"], PENDING)

    def test_um_item_pode_valer_para_varios_alvos(self):
        self.store.link("x", "family", "f1", "Família 1")
        self.store.link("x", "rule", "r1", "Regra 1")
        self.assertEqual(len(self.store.targets_of("x")), 2)
        self.assertEqual(self.store.get("x")["status"], LINKED)

    def test_vincular_duas_vezes_o_mesmo_alvo_nao_duplica(self):
        self.store.link("x", "family", "f1", "Família 1")
        self.store.link("x", "family", "f1", "Família 1")
        self.assertEqual(len(self.store.targets_of("x")), 1)

    def test_busca_reversa_por_alvo(self):
        self.store.link("a", "family", "f1")
        self.store.link("b", "family", "f1")
        self.store.link("c", "rule", "r1")
        self.assertEqual(self.store.entries_for_target("family", "f1"), ["a", "b"])

    def test_desfazer_o_ultimo_vinculo_devolve_ao_pendente(self):
        self.store.link("x", "family", "f1")
        self.assertEqual(self.store.unlink("x", "family", "f1")["status"], PENDING)
        self.assertEqual(self.store.get("x")["status"], PENDING)

    def test_descartar_e_reversivel(self):
        self.store.set_status("x", REJECTED)
        self.assertEqual(self.store.get("x")["status"], REJECTED)
        self.store.set_status("x", PENDING)
        self.assertEqual(self.store.get("x")["status"], PENDING)

    def test_estado_invalido_e_recusado_com_a_lista(self):
        with self.assertRaises(LinkError) as ctx:
            self.store.set_status("x", "aprovado")
        self.assertIn("linked", str(ctx.exception))

    def test_tipo_de_alvo_invalido_e_recusado(self):
        with self.assertRaises(LinkError):
            self.store.link("x", "host", "10501")

    def test_arquivo_corrompido_nao_derruba_a_leitura(self):
        self.store.path.write_text("{isto não é json", encoding="utf-8")
        self.assertEqual(self.store.all(), {})


# ----------------------------------------------------------------- via HTTP
class ServidorKb:
    def __init__(self, output_dir: str, docs_dir: str, catalog_file: str):
        self.servidor = serve(output_dir=output_dir, docs_dir=docs_dir, host="127.0.0.1", port=0,
                              catalog_file=catalog_file)
        self.porta = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def pedir(self, caminho: str, method: str = "GET", corpo: Any = None) -> tuple[int, Any]:
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.porta}{caminho}", data=dados,
                                     method=method,
                                     headers={"Content-Type": "application/json"} if dados else {})
        try:
            with urllib.request.urlopen(req, timeout=10) as resposta:
                return resposta.status, json.loads(resposta.read())
        except urllib.error.HTTPError as erro:
            return erro.code, json.loads(erro.read())

    def parar(self) -> None:
        self.servidor.shutdown()
        self.servidor.server_close()


class TestKbViaHTTP(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.docs = str(base / "docs" / "alerts")
        Path(self.docs).mkdir(parents=True)
        montar_snapshot(self._tmp.name)
        self.catalogo = escrever_catalogo(base)
        self.srv = ServidorKb(self._tmp.name, self.docs, str(self.catalogo))

    def tearDown(self):
        self.srv.parar()
        self._tmp.cleanup()

    def get(self, caminho: str) -> Any:
        status, dados = self.srv.pedir(caminho)
        self.assertEqual(status, 200, dados)
        return dados

    def _id(self, nome: str) -> str:
        return next(i["id"] for i in self.get("/api/kb")["items"] if i["name"] == nome)

    def test_lista_traz_os_itens_e_a_matriz(self):
        dados = self.get("/api/kb")
        self.assertEqual(dados["facets"]["total_unfiltered"], 3)
        self.assertEqual(len(dados["escalation"]), 2)
        self.assertTrue(all(i["link"]["status"] == PENDING for i in dados["items"]))

    def test_detalhe_traz_previa_e_o_que_falta(self):
        dados = self.get(f"/api/kb/{self._id('Serviço parado')}")
        self.assertIn("meaning", dados["preview"]["operational"])
        self.assertIn("meaning", dados["preview"]["field_sources"])
        self.assertTrue(dados["missing_from_wiki"])
        self.assertIn("Casar texto não prova", dados["disclaimer"])

    def test_vincular_cria_ficha_como_rascunho_e_nao_como_documentada(self):
        entrada = self._id("/var: Disk space is critically low")
        alvo = next(s for s in self.get(f"/api/kb/{entrada}")["suggestions"] if s["kind"] == "family")
        status, resposta = self.srv.pedir(f"/api/kb/{entrada}/link", "POST",
                                          {"kind": "family", "target_id": alvo["target_id"]})
        self.assertEqual(status, 200, resposta)
        self.assertEqual(resposta["procedure_status"], "draft")
        self.assertIn("meaning", resposta["written_fields"])

        doc = AlertRepository(self.docs).get(resposta["doc_key"])
        self.assertIsNotNone(doc)
        self.assertEqual(doc.operational["meaning"], "Partição /var em nível crítico.")
        self.assertEqual(doc.operational["imported_from"]["source"], "wiki-noc")
        self.assertEqual(doc.operational["imported_from"]["entry_id"], entrada)
        # A procedência precisa dizer de onde veio CADA campo.
        self.assertIn("meaning", doc.operational["imported_from"]["field_sources"])

    def test_familia_vinculada_passa_a_mostrar_o_item_do_wiki(self):
        entrada = self._id("/var: Disk space is critically low")
        alvo = next(s for s in self.get(f"/api/kb/{entrada}")["suggestions"] if s["kind"] == "family")
        self.srv.pedir(f"/api/kb/{entrada}/link", "POST",
                       {"kind": "family", "target_id": alvo["target_id"]})
        familia = self.get(f"/api/families/{alvo['target_id']}")
        self.assertEqual([e["id"] for e in familia["wiki_entries"]], [entrada])

    def test_importar_nao_sobrescreve_o_que_uma_pessoa_escreveu(self):
        entrada = self._id("/var: Disk space is critically low")
        alvo = next(s for s in self.get(f"/api/kb/{entrada}")["suggestions"] if s["kind"] == "family")
        chave = self.get(f"/api/families/{alvo['target_id']}")["key"]

        status, _ = self.srv.pedir(f"/api/procedures/{alvo['target_id']}", "POST",
                                   {"operational": {"doc_status": "pending_review",
                                                    "meaning": "Escrito pela equipe"}})
        self.assertEqual(status, 200)

        _, resposta = self.srv.pedir(f"/api/kb/{entrada}/link", "POST",
                                     {"kind": "family", "target_id": alvo["target_id"]})
        self.assertIn("meaning", resposta["preserved_fields"])
        doc = AlertRepository(self.docs).get(chave)
        self.assertEqual(doc.operational["meaning"], "Escrito pela equipe")
        # O resto do wiki entrou nos campos que estavam vazios.
        self.assertEqual(doc.operational["probable_cause"], "Crescimento de logs.")

    def test_item_sem_correspondencia_vira_ficha_manual(self):
        entrada = self._id("STALL")
        detalhe = self.get(f"/api/kb/{entrada}")
        self.assertEqual(detalhe["suggestions"], [],
                         "STALL não deveria casar com nada neste snapshot")

        status, resposta = self.srv.pedir(f"/api/kb/{entrada}/manual", "POST", {})
        self.assertEqual(status, 200, resposta)
        self.assertEqual(resposta["doc_key"], kb_doc_key(entrada))

        doc = AlertRepository(self.docs).get(kb_doc_key(entrada))
        self.assertEqual(doc.scope, "manual")
        self.assertFalse(doc.present_in_zabbix)
        self.assertEqual(doc.operational["routing"]["team"], "Sobreaviso MSMonitor")
        self.assertEqual(self.get("/api/kb/" + entrada)["link"]["status"], MANUAL)

    def test_desfazer_vinculo_preserva_a_ficha(self):
        entrada = self._id("/var: Disk space is critically low")
        alvo = next(s for s in self.get(f"/api/kb/{entrada}")["suggestions"] if s["kind"] == "family")
        _, criado = self.srv.pedir(f"/api/kb/{entrada}/link", "POST",
                                   {"kind": "family", "target_id": alvo["target_id"]})
        self.srv.pedir(f"/api/kb/{entrada}/unlink", "POST",
                       {"kind": "family", "target_id": alvo["target_id"]})
        self.assertEqual(self.get(f"/api/kb/{entrada}")["link"]["status"], PENDING)
        self.assertIsNotNone(AlertRepository(self.docs).get(criado["doc_key"]))

    def test_descartar_e_desfazer(self):
        entrada = self._id("STALL")
        self.srv.pedir(f"/api/kb/{entrada}/status", "POST", {"status": "rejected"})
        self.assertEqual(self.get(f"/api/kb/{entrada}")["link"]["status"], REJECTED)
        self.srv.pedir(f"/api/kb/{entrada}/status", "POST", {"status": "pending"})
        self.assertEqual(self.get(f"/api/kb/{entrada}")["link"]["status"], PENDING)

    def test_alvo_inexistente_e_404_e_nao_500(self):
        entrada = self._id("STALL")
        status, dados = self.srv.pedir(f"/api/kb/{entrada}/link", "POST",
                                       {"kind": "family", "target_id": "nao-existe"})
        self.assertEqual(status, 404, dados)

    def test_item_inexistente_e_404(self):
        status, _ = self.srv.pedir("/api/kb/nao-existe")
        self.assertEqual(status, 404)

    def test_dashboard_mostra_a_base_do_noc(self):
        kb = self.get("/api/dashboard")["knowledge_base"]
        self.assertEqual(kb["total"], 3)
        self.assertEqual(kb["pending"], 3)

    def test_metodos_de_escrita_no_zabbix_continuam_ausentes(self):
        """A base de conhecimento não abriu nenhuma porta para o Zabbix."""
        for rota in ("/api/kb", "/api/dashboard"):
            status, _ = self.srv.pedir(rota, "PUT", {})
            self.assertEqual(status, 405)


class TestSemCatalogo(unittest.TestCase):
    """Sem wiki nenhum o sistema continua inteiro — a aba só não aparece."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.docs = str(Path(self._tmp.name) / "docs")
        Path(self.docs).mkdir(parents=True)
        montar_snapshot(self._tmp.name)
        self.srv = ServidorKb(self._tmp.name, self.docs,
                              str(Path(self._tmp.name) / "sem-catalogo.md"))

    def tearDown(self):
        self.srv.parar()
        self._tmp.cleanup()

    def test_kb_responde_404_com_instrucao(self):
        status, dados = self.srv.pedir("/api/kb")
        self.assertEqual(status, 404)
        self.assertIn("catalogo-noc.md", dados["error"])

    def test_dashboard_omite_o_bloco_em_vez_de_falhar(self):
        status, dados = self.srv.pedir("/api/dashboard")
        self.assertEqual(status, 200)
        self.assertIsNone(dados["knowledge_base"])


class TestCatalogoRealDoRepositorio(unittest.TestCase):
    """O catálogo versionado precisa continuar legível — ele é uma fonte."""

    def test_le_o_catalogo_do_noc(self):
        caminho = Path("docs/knowledge/catalogo-noc.md")
        if not caminho.is_file():
            self.skipTest("catálogo do NOC não está neste checkout")
        catalogo = parse_catalog(caminho)
        self.assertGreaterEqual(len(catalogo.entries), 20)
        self.assertGreaterEqual(len(catalogo.escalation), 8)
        # Todo item precisa de nome, categoria e ação — sem isso não é catálogo.
        for entrada in catalogo.entries:
            self.assertTrue(entrada.name)
            self.assertTrue(entrada.category)
            self.assertTrue(entrada.action, f"{entrada.name} sem ação")
            self.assertTrue(entrada.team, f"{entrada.name} sem fila")


if __name__ == "__main__":
    unittest.main()
