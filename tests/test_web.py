"""Interface web (Fase 3): API de leitura, filtros, paginação e segurança.

Os testes sobem o servidor de verdade e falam HTTP com ele. Testar as funções
de `api` diretamente deixaria de fora o roteamento, os códigos de status e as
travas do handler — que é justamente onde mora a garantia de somente leitura.
"""

from __future__ import annotations

import ast
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src.collect import collect_raw
from src.core.models import AlertDoc, build_family_key
from src.core.repository import AlertRepository
from src.normalize import normalize_snapshot
from src.snapshot import write_json, write_snapshot
from src.web.readmodel import ReadModel, paginate, resolve_snapshot
from src.web.server import serve
from src.zabbix_client import ZabbixReadOnlyClient
from tests.fixtures.fake_zabbix import FakeZabbix


def montar_snapshot(base: str) -> Path:
    """Coleta do Zabbix falso e grava um snapshot completo em `base`."""
    cliente = ZabbixReadOnlyClient("https://zabbix.local", api_token="fake-token", transport=FakeZabbix())
    raw = collect_raw(cliente)
    normalizado = normalize_snapshot(raw)
    caminhos = write_snapshot(base, raw, normalizado)
    write_json(caminhos["snapshot_dir"] / "report.json", {
        "meta": raw.meta, "counts": {"templates": len(raw.data["templates"])},
        "normalization": normalizado.stats, "collisions": normalizado.collisions,
        "paths": {k: str(v) for k, v in caminhos.items()},
    })
    return caminhos["snapshot_dir"]


class ServidorDeTeste:
    """Sobe o servidor numa porta livre e fala HTTP com ele."""

    def __init__(self, output_dir: str, docs_dir: str):
        self.servidor = serve(output_dir=output_dir, docs_dir=docs_dir, host="127.0.0.1", port=0)
        self.porta = self.servidor.server_address[1]
        self.thread = threading.Thread(target=self.servidor.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.porta}"

    def pedir(self, caminho: str, method: str = "GET", corpo: Any = None) -> tuple[int, Any]:
        dados = json.dumps(corpo).encode() if corpo is not None else None
        requisicao = urllib.request.Request(
            f"{self.base}{caminho}", data=dados, method=method,
            headers={"Content-Type": "application/json"} if dados else {},
        )
        try:
            with urllib.request.urlopen(requisicao, timeout=10) as resposta:
                bruto = resposta.read()
                tipo = resposta.headers.get("Content-Type", "")
                return resposta.status, json.loads(bruto) if "json" in tipo else bruto.decode("utf-8")
        except urllib.error.HTTPError as erro:
            bruto = erro.read()
            try:
                return erro.code, json.loads(bruto)
            except json.JSONDecodeError:
                return erro.code, bruto.decode("utf-8", "replace")

    def parar(self) -> None:
        self.servidor.shutdown()
        self.servidor.server_close()


class BaseWeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.output = cls._tmp.name
        cls.docs = str(Path(cls._tmp.name) / "docs")
        Path(cls.docs).mkdir(parents=True, exist_ok=True)
        montar_snapshot(cls.output)
        cls.srv = ServidorDeTeste(cls.output, cls.docs)

    @classmethod
    def tearDownClass(cls):
        cls.srv.parar()
        cls._tmp.cleanup()

    def get(self, caminho: str) -> Any:
        status, dados = self.srv.pedir(caminho)
        self.assertEqual(status, 200, dados)
        return dados


class TestDashboard(BaseWeb):
    def test_cards_e_indicadores(self):
        dados = self.get("/api/dashboard")
        cards = {c["key"]: c for c in dados["cards"]}

        self.assertEqual(cards["alerts"]["value"], 6)
        self.assertEqual(cards["hosts"]["value"], 3)
        self.assertEqual(cards["families"]["value"], 5)
        self.assertGreater(cards["without_procedure"]["value"], 0)
        # Todo card leva a uma lista — o item 4 pede indicadores clicáveis.
        for card in dados["cards"]:
            self.assertTrue(card["href"].startswith("/"), card)

    def test_severidades_somam_o_total(self):
        dados = self.get("/api/dashboard")
        self.assertEqual(sum(s["value"] for s in dados["severities"]), 6)

    def test_top_familias_tem_procedimento(self):
        dados = self.get("/api/dashboard")
        self.assertTrue(dados["top_families"])
        for familia in dados["top_families"]:
            self.assertIn(familia["procedure"]["status"], ("missing", "draft", "documented"))


class TestAlertas(BaseWeb):
    def test_lista_paginada(self):
        dados = self.get("/api/alerts?per_page=2")
        self.assertEqual(len(dados["items"]), 2)
        self.assertEqual(dados["pagination"]["total"], 6)
        self.assertEqual(dados["pagination"]["pages"], 3)
        self.assertTrue(dados["pagination"]["has_next"])

    def test_paginas_nao_repetem_nem_perdem_alertas(self):
        vistos = []
        for pagina in (1, 2, 3):
            vistos += [a["id"] for a in self.get(f"/api/alerts?per_page=2&page={pagina}")["items"]]
        self.assertEqual(len(vistos), 6)
        self.assertEqual(len(set(vistos)), 6)

    def test_busca_textual(self):
        dados = self.get("/api/alerts?q=wazuh")
        self.assertTrue(dados["items"])
        for item in dados["items"]:
            texto = f"{item['description']} {item['host']['name']} {item['alert_key']}".lower()
            self.assertIn("wazuh", texto)

    def test_busca_ignora_acento_e_caixa(self):
        com = self.get("/api/alerts?q=servi%C3%A7o")["pagination"]["total"]
        sem = self.get("/api/alerts?q=SERVICO")["pagination"]["total"]
        self.assertEqual(com, sem)
        self.assertGreater(com, 0)

    def test_filtro_por_severidade(self):
        dados = self.get("/api/alerts?severity=Disaster")
        self.assertTrue(dados["items"])
        for item in dados["items"]:
            self.assertEqual(item["severity"], "Disaster")

    def test_filtro_lld(self):
        somente = self.get("/api/alerts?discovered=1")
        nenhum = self.get("/api/alerts?discovered=0")
        self.assertTrue(all(i["discovered"] for i in somente["items"]))
        self.assertTrue(all(not i["discovered"] for i in nenhum["items"]))
        self.assertEqual(somente["pagination"]["total"] + nenhum["pagination"]["total"], 6)

    def test_filtro_sem_procedimento(self):
        dados = self.get("/api/alerts?procedure=missing")
        self.assertEqual(dados["pagination"]["total"], 6, "nenhuma ficha existe ainda")

    def test_filtros_combinam(self):
        dados = self.get("/api/alerts?discovered=0&comment=1")
        for item in dados["items"]:
            self.assertFalse(item["discovered"])
            self.assertTrue(item["has_comment"])

    def test_filtro_invalido_e_400_com_explicacao(self):
        status, dados = self.srv.pedir("/api/alerts?severity=Catastrofica")
        self.assertEqual(status, 400)
        self.assertIn("severity", dados["error"])

    def test_filtro_de_colisao(self):
        dados = self.get("/api/alerts?collision=1")
        self.assertTrue(dados["items"])
        self.assertTrue(all(i["collision"] for i in dados["items"]))


class TestDetalheDoAlerta(BaseWeb):
    def setUp(self):
        self.alerta = self.get("/api/alerts?per_page=1")["items"][0]

    def test_secoes_do_detalhe(self):
        d = self.get(f"/api/alerts/{self.alerta['id']}")
        for secao in ("identification", "origin", "condition", "severity", "items",
                      "dependencies", "comments", "tags", "procedure"):
            self.assertIn(secao, d)
        self.assertEqual(d["id"], self.alerta["id"])
        self.assertTrue(d["identification"]["alert_key"])
        self.assertTrue(d["identification"]["source_hash"].startswith("sha256:"))

    def test_alerta_inexistente_e_404(self):
        status, dados = self.srv.pedir("/api/alerts/999999")
        self.assertEqual(status, 404)
        self.assertIn("não existe", dados["error"])

    def test_template_ausente_e_none_e_nao_erro(self):
        """0 templates é estado válido: o usuário da API pode não enxergá-los."""
        d = self.get(f"/api/alerts/{self.alerta['id']}")
        self.assertIn("source_template", d["origin"])
        self.assertNotIn("error", d)


class TestFamilias(BaseWeb):
    def test_lista_ordenada_por_alertas(self):
        dados = self.get("/api/families")
        contagens = [f["alerts"] for f in dados["items"]]
        self.assertEqual(contagens, sorted(contagens, reverse=True))

    def test_detalhe_agrupa_os_alertas(self):
        familia = self.get("/api/families")["items"][0]
        d = self.get(f"/api/families/{familia['id']}")

        self.assertEqual(d["alerts"], familia["alerts"])
        self.assertEqual(len(d["hosts_list"]), d["hosts"])
        self.assertTrue(d["expressions"])
        self.assertEqual(len(d["alerts_page"]["items"]), min(d["alerts"], 50))

    def test_familia_multi_host_nao_vira_uma_ficha_por_host(self):
        """Item 7: milhares de triggers da mesma regra são UMA unidade."""
        familias = self.get("/api/families")["items"]
        multi = [f for f in familias if f["hosts"] > 1]
        self.assertTrue(multi, "o Zabbix falso tem um trigger de template em 2 hosts")
        self.assertEqual(multi[0]["alerts"], 2)
        self.assertEqual(multi[0]["hosts"], 2)

    def test_familia_inexistente_e_404(self):
        status, _ = self.srv.pedir("/api/families/naoexiste")
        self.assertEqual(status, 404)


class TestHostsEGrupos(BaseWeb):
    def test_lista_de_hosts(self):
        dados = self.get("/api/hosts")
        self.assertEqual(dados["pagination"]["total"], 3)
        for host in dados["items"]:
            self.assertIn("procedures_missing", host)

    def test_detalhe_do_host(self):
        host = self.get("/api/hosts")["items"][0]
        d = self.get(f"/api/hosts/{host['id']}")
        self.assertEqual(d["alerts"], host["alerts"])
        self.assertTrue(d["families_list"])
        self.assertEqual(len(d["alerts_page"]["items"]), min(host["alerts"], 50))

    def test_lista_de_grupos(self):
        dados = self.get("/api/host-groups")
        self.assertEqual(dados["pagination"]["total"], 3)

    def test_host_em_varios_grupos_nao_e_duplicado_dentro_do_grupo(self):
        """Item 5: os números de um grupo não podem inflar artificialmente."""
        grupos = {g["name"]: g for g in self.get("/api/host-groups")["items"]}
        infra = grupos["Infraestrutura"]
        self.assertEqual(infra["hosts"], 3, "os 3 hosts do fake estão em Infraestrutura")
        self.assertEqual(infra["alerts"], 6)

        detalhe = self.get(f"/api/host-groups/{infra['id']}")
        ids = [h["id"] for h in detalhe["hosts_list"]]
        self.assertEqual(len(ids), len(set(ids)), "host repetido dentro do grupo")

    def test_grupo_filtra_os_alertas(self):
        grupos = {g["name"]: g for g in self.get("/api/host-groups")["items"]}
        detalhe = self.get(f"/api/host-groups/{grupos['SIEM']['id']}")
        for alerta in detalhe["alerts_page"]["items"]:
            self.assertIn("SIEM", alerta["host_groups"])


class TestColisoes(BaseWeb):
    def test_lista_com_detalhes(self):
        dados = self.get("/api/collisions")
        self.assertTrue(dados["items"])
        colisao = dados["items"][0]
        for campo in ("alert_key", "triggers", "hosts", "severities", "descriptions", "occurrences"):
            self.assertIn(campo, colisao)
        self.assertGreaterEqual(colisao["triggers"], 2)

    def test_nota_diz_que_colisao_nao_e_veredito(self):
        dados = self.get("/api/collisions")
        self.assertIn("análise", dados["note"])
        self.assertIn("PODE", dados["note"])


class TestStatus(BaseWeb):
    def test_status_descreve_a_coleta(self):
        dados = self.get("/api/status")
        self.assertTrue(dados["read_only"])
        self.assertEqual(dados["counts"]["alerts"], 6)
        self.assertEqual(dados["counts"]["hosts"], 3)
        self.assertIn("collection", dados)
        self.assertTrue(dados["snapshot"]["name"])
        self.assertTrue(dados["available_snapshots"])

    def test_status_registra_a_redacao(self):
        dados = self.get("/api/status")
        self.assertIn("redaction", dados["snapshot"])


class TestBuscaGlobal(BaseWeb):
    def test_agrupa_por_tipo(self):
        dados = self.get("/api/search?q=wazuh")
        tipos = {g["kind"] for g in dados["groups"]}
        self.assertIn("alerts", tipos)
        self.assertIn("hosts", tipos)
        for grupo in dados["groups"]:
            self.assertGreater(grupo["total"], 0)

    def test_busca_vazia_nao_quebra(self):
        dados = self.get("/api/search?q=")
        self.assertEqual(dados["groups"], [])

    def test_termo_sem_resultado(self):
        dados = self.get("/api/search?q=zzzzznaoexistezzzz")
        self.assertEqual(dados["groups"], [])


class TestProcedimentos(unittest.TestCase):
    """Ambiente próprio POR TESTE: estes testes escrevem fichas em disco.

    Compartilhar o `docs/` entre eles faria uma ficha criada num teste mudar a
    contagem do seguinte — e o teste passaria ou falharia conforme a ordem.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output = self._tmp.name
        self.docs = str(Path(self._tmp.name) / "docs")
        Path(self.docs).mkdir(parents=True, exist_ok=True)
        montar_snapshot(self.output)
        self.srv = ServidorDeTeste(self.output, self.docs)

    def tearDown(self):
        self.srv.parar()
        self._tmp.cleanup()

    def get(self, caminho: str) -> Any:
        status, dados = self.srv.pedir(caminho)
        self.assertEqual(status, 200, dados)
        return dados

    def test_lista_com_contagem_por_estado(self):
        dados = self.get("/api/procedures")
        estados = {f["status"]: f["value"] for f in dados["facets"]["by_status"]}
        self.assertEqual(estados["missing"], 5, "as 5 famílias começam sem procedimento")
        self.assertEqual(estados["documented"], 0)

    def test_gravar_procedimento_local(self):
        familia = self.get("/api/families")["items"][0]
        status, dados = self.srv.pedir(
            f"/api/procedures/{familia['id']}", "POST",
            {"operational": {"doc_status": "pending_review", "meaning": "Disco cheio na raiz",
                             "actions": ["limpar logs", "escalar se persistir"]}},
        )
        self.assertEqual(status, 200, dados)
        self.assertTrue(dados["saved"])
        self.assertEqual(dados["procedure_status"], "draft")

        # A ficha foi para docs/alerts/, e a leitura seguinte já a enxerga.
        detalhe = self.get(f"/api/families/{familia['id']}")
        self.assertEqual(detalhe["procedure"]["status"], "draft")
        self.assertEqual(detalhe["procedure"]["operational"]["meaning"], "Disco cheio na raiz")

    def test_marcar_documentado_sem_campos_minimos_e_recusado(self):
        """A máquina de estados da ETAPA 2 continua valendo pela interface."""
        familia = self.get("/api/families")["items"][1]
        status, dados = self.srv.pedir(
            f"/api/procedures/{familia['id']}", "POST",
            {"operational": {"doc_status": "documented", "meaning": "só isso"}},
        )
        self.assertEqual(status, 422, dados)
        self.assertIn("Campos mínimos", dados["error"])

    def test_procedimento_de_familia_inexistente_e_404(self):
        status, _ = self.srv.pedir("/api/procedures/naoexiste", "POST", {"operational": {}})
        self.assertEqual(status, 404)

    def test_corpo_invalido_e_400(self):
        familia = self.get("/api/families")["items"][0]
        status, dados = self.srv.pedir(f"/api/procedures/{familia['id']}", "POST", {"operational": "texto"})
        self.assertEqual(status, 400)


class TestSeguranca(BaseWeb):
    def test_a_web_nao_importa_o_cliente_zabbix(self):
        """A garantia de somente leitura é estrutural, não uma promessa.

        Verificado nos IMPORTS via AST, não por substring: a palavra
        `zabbix_client` aparece nas docstrings justamente para explicar que ela
        não é importada, e um teste textual acusaria isso como violação.
        """
        proibidos = {"zabbix_client", "requests", "http.client", "urllib.request"}
        for arquivo in (Path(__file__).resolve().parents[1] / "src" / "web").rglob("*.py"):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                if isinstance(no, ast.Import):
                    nomes = [alias.name for alias in no.names]
                elif isinstance(no, ast.ImportFrom):
                    nomes = [no.module or ""]
                else:
                    continue
                for nome in nomes:
                    raiz = nome.lstrip(".")
                    self.assertNotIn(
                        raiz, proibidos,
                        f"{arquivo.name} importa {nome}: a interface não pode falar com o Zabbix",
                    )

    def test_nenhuma_credencial_e_servida(self):
        for caminho in ("/api/status", "/api/dashboard", "/api/alerts", "/app.js", "/index.html"):
            _, corpo = self.srv.pedir(caminho)
            texto = json.dumps(corpo) if isinstance(corpo, (dict, list)) else corpo
            for proibido in ("ZABBIX_API_TOKEN", "ZABBIX_PASSWORD", "api_token", "fake-token"):
                self.assertNotIn(proibido, texto, f"{proibido} vazou em {caminho}")

    def test_metodos_de_escrita_nao_existem(self):
        for metodo in ("PUT", "DELETE"):
            status, _ = self.srv.pedir("/api/alerts", metodo)
            self.assertEqual(status, 405, metodo)

    def test_post_so_e_aceito_em_procedimentos(self):
        for caminho in ("/api/alerts", "/api/status", "/api/families"):
            status, dados = self.srv.pedir(caminho, "POST", {})
            self.assertEqual(status, 404, f"{caminho} não pode aceitar POST: {dados}")

    def test_nao_existe_rota_que_escreva_no_zabbix(self):
        for caminho in ("/api/trigger.create", "/api/zabbix", "/api/collect", "/api/configuration.import"):
            status, _ = self.srv.pedir(caminho, "POST", {})
            self.assertEqual(status, 404, caminho)

    def test_estatico_nao_escapa_do_diretorio(self):
        for tentativa in ("/../../../etc/passwd", "/..%2f..%2fetc%2fpasswd", "/static/../../../main.py"):
            status, corpo = self.srv.pedir(tentativa)
            # Ou 404, ou o index do app — nunca um arquivo de fora.
            self.assertNotIn("ZABBIX_URL", str(corpo))
            self.assertNotIn("def main(", str(corpo))

    def test_cabecalhos_de_seguranca(self):
        requisicao = urllib.request.Request(f"{self.srv.base}/api/status")
        with urllib.request.urlopen(requisicao, timeout=10) as resposta:
            self.assertIn("default-src 'self'", resposta.headers["Content-Security-Policy"])
            self.assertEqual(resposta.headers["X-Content-Type-Options"], "nosniff")


class TestInterfaceEstatica(BaseWeb):
    def test_index_e_servido(self):
        _, corpo = self.srv.pedir("/")
        self.assertIn("Zabbix-Wiki", corpo)
        self.assertIn("/app.js", corpo)

    def test_rota_do_app_devolve_o_index(self):
        """/alerts/123 é rota do navegador: o servidor devolve o app."""
        _, corpo = self.srv.pedir("/alerts/100")
        self.assertIn("<title>Zabbix-Wiki</title>", corpo)

    def test_css_e_js_com_o_mime_certo(self):
        requisicao = urllib.request.Request(f"{self.srv.base}/app.css")
        with urllib.request.urlopen(requisicao, timeout=10) as resposta:
            self.assertIn("text/css", resposta.headers["Content-Type"])


class TestEscopoViaHTTP(unittest.TestCase):
    """O escopo na URL (item 9): compartilhável, recarregável, com filtros."""

    def setUp(self):
        from tests.test_scope import GIGANTE, montar_ambiente

        self.gigante = GIGANTE
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        montar_ambiente(base)
        docs = base / "docs"
        docs.mkdir(exist_ok=True)

        escopos = base / "scopes.json"
        escopos.write_text(json.dumps({
            "default": "noc",
            "scopes": [{"id": "noc", "label": "NOC", "exclude_hosts": [GIGANTE]}],
        }), encoding="utf-8")

        self.servidor = serve(output_dir=str(base), docs_dir=str(docs),
                              host="127.0.0.1", port=0, scopes_file=str(escopos))
        self.porta = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def tearDown(self):
        self.servidor.shutdown()
        self.servidor.server_close()
        self._tmp.cleanup()

    def get(self, caminho: str) -> Any:
        with urllib.request.urlopen(f"http://127.0.0.1:{self.porta}{caminho}", timeout=10) as resposta:
            return json.loads(resposta.read())

    def test_escopo_padrao_e_o_do_scopes_json(self):
        dados = self.get("/api/dashboard")
        self.assertEqual(dados["scope"]["id"], "noc")
        self.assertEqual(dados["scope"]["alerts_in_scope"], 40)
        self.assertEqual(dados["environment"]["alerts"], 240)

    def test_scope_all_na_url_traz_o_ambiente_inteiro(self):
        dados = self.get("/api/alerts?scope=all")
        self.assertEqual(dados["pagination"]["total"], 240)
        self.assertEqual(self.get("/api/alerts?scope=noc")["pagination"]["total"], 40)

    def test_escopo_combina_com_filtros(self):
        """`/alerts?scope=noc&severity=Disaster` precisa aplicar os dois."""
        no_escopo = self.get("/api/alerts?scope=noc&severity=Disaster")["pagination"]["total"]
        completo = self.get("/api/alerts?scope=all&severity=Disaster")["pagination"]["total"]
        self.assertEqual(no_escopo, 3, "um Disaster por host do NOC")
        self.assertEqual(completo, 3)
        self.assertTrue(all(i["severity"] == "Disaster"
                            for i in self.get("/api/alerts?scope=noc&severity=Disaster")["items"]))

    def test_host_fora_do_escopo_nao_aparece_na_lista(self):
        nomes = {h["name"] for h in self.get("/api/hosts?scope=noc")["items"]}
        self.assertNotIn(self.gigante, nomes)
        self.assertIn(self.gigante, {h["name"] for h in self.get("/api/hosts?scope=all")["items"]})

    def test_busca_avisa_sobre_o_que_esta_fora(self):
        dados = self.get("/api/search?scope=noc&q=job")
        self.assertGreater(dados["out_of_scope_alerts"], 0)
        self.assertEqual(dados["scope"]["id"], "noc")

    def test_colisoes_respeitam_o_escopo(self):
        self.assertEqual(self.get("/api/collisions?scope=noc")["pagination"]["total"], 1)
        self.assertEqual(self.get("/api/collisions?scope=all")["pagination"]["total"], 2)

    def test_status_mostra_a_coleta_inteira_em_qualquer_escopo(self):
        for escopo in ("noc", "all"):
            dados = self.get(f"/api/status?scope={escopo}")
            self.assertEqual(dados["counts"]["alerts"], 240, escopo)
            self.assertEqual(dados["environment"]["alerts"], 240, escopo)

    def test_endpoint_de_escopos(self):
        dados = self.get("/api/scopes")
        ids = {e["id"] for e in dados["scopes"]}
        self.assertEqual(ids, {"noc", "all"})
        self.assertEqual(dados["default"], "noc")
        noc = next(e for e in dados["scopes"] if e["id"] == "noc")
        self.assertTrue(noc["is_default"])
        self.assertEqual(noc["mode"], "exclude")

    def test_escopo_invalido_e_400(self):
        try:
            self.get("/api/alerts?scope=inexistente")
            self.fail("deveria ter recusado")
        except urllib.error.HTTPError as erro:
            self.assertEqual(erro.code, 400)
            self.assertIn("inexistente", json.loads(erro.read())["error"])

    def test_trocar_de_escopo_nao_altera_o_snapshot(self):
        alerts = Path(self._tmp.name) / "snapshots" / "20260905_181510" / "normalized" / "alerts.json"
        antes = (alerts.read_bytes(), alerts.stat().st_mtime)
        for escopo in ("noc", "all", "noc"):
            self.get(f"/api/dashboard?scope={escopo}")
        self.assertEqual((alerts.read_bytes(), alerts.stat().st_mtime), antes,
                         "o escopo é leitura: nenhum byte do snapshot pode mudar")


class TestSemSnapshot(unittest.TestCase):
    def test_mensagem_util_quando_nao_ha_coleta(self):
        with tempfile.TemporaryDirectory() as tmp:
            servidor = ServidorDeTeste(tmp, str(Path(tmp) / "docs"))
            try:
                status, dados = servidor.pedir("/api/dashboard")
                self.assertEqual(status, 503)
                self.assertIn("collect", dados["hint"])
            finally:
                servidor.parar()


class TestReadModel(unittest.TestCase):
    def test_paginate(self):
        itens = list(range(100))
        pagina, meta = paginate(itens, 3, 10)
        self.assertEqual(pagina, list(range(20, 30)))
        self.assertEqual(meta["pages"], 10)

    def test_paginate_limita_pagina_fora_do_intervalo(self):
        _, meta = paginate(list(range(10)), 999, 10)
        self.assertEqual(meta["page"], 1)

    def test_familia_usa_a_mesma_chave_do_reconcile(self):
        """Se divergirem, a interface mostraria 'sem procedimento' para fichas que existem."""
        with tempfile.TemporaryDirectory() as tmp:
            caminho = montar_snapshot(tmp)
            modelo = ReadModel(caminho, docs_dir=str(Path(tmp) / "docs"))
            for familia in modelo.families.values():
                alerta = modelo.by_trigger[familia.alert_ids[0]]
                self.assertEqual(familia.key, build_family_key(alerta))

    def test_ficha_existente_e_encontrada_pela_interface(self):
        with tempfile.TemporaryDirectory() as tmp:
            caminho = montar_snapshot(tmp)
            docs = str(Path(tmp) / "docs")
            modelo = ReadModel(caminho, docs_dir=docs)
            familia = next(iter(modelo.families.values()))

            doc = AlertDoc.from_collected_alert(modelo.by_trigger[familia.alert_ids[0]])
            doc.alert_key = familia.key
            doc.operational["doc_status"] = "pending_review"
            AlertRepository(docs).save(doc)

            recarregado = ReadModel(caminho, docs_dir=docs)
            self.assertEqual(recarregado.procedure_of_family(familia.id)["status"], "draft")

    def test_snapshot_parcial_nao_e_escolhido_por_padrao(self):
        with tempfile.TemporaryDirectory() as tmp:
            bom = montar_snapshot(tmp)
            parcial = Path(tmp) / "snapshots" / "29990101_000000__parcial"
            (parcial / "normalized").mkdir(parents=True)
            (parcial / "normalized" / "alerts.json").write_text('{"alerts": []}', encoding="utf-8")

            escolhido = resolve_snapshot(tmp)
            self.assertEqual(escolhido, bom, "um parcial não pode virar a base de consulta")


if __name__ == "__main__":
    unittest.main()
