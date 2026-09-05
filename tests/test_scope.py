"""Escopo operacional: o NOC vê um recorte, o snapshot continua inteiro.

O cenário reproduz o desequilíbrio real: um host domina o ambiente
(`Control-M PRD Votorantim`, ~86% dos alertas no ambiente do usuário) e precisa
sair da visão do NOC sem sair do snapshot.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.scope import EVERYTHING, OperationalScope, ScopeError, load_scopes, parse_scopes
from src.web import api
from src.web.readmodel import ReadModel

#: Proporções propositalmente parecidas com o ambiente real: um host gigante,
#: alguns hosts normais, e famílias de LLD com muitas instâncias.
GIGANTE = "Control-M PRD Votorantim"
VIZINHOS = ["Control-M DEV Votorantim", "Control-M SaaS Master"]
NOC_HOSTS = ["Vibe - Zabbix server", "Vibe - Proxy [Fortigate]", "Saq - AWS"]


def _alerta(indice: int, host: str, hostid: str, familia: str, severidade: str = "Warning",
            lld: bool = True, grupos: list[str] | None = None) -> dict[str, Any]:
    return {
        "alert_key": f"{hostid}|{familia}-{indice}",
        "alert_key_strategy": "prototype+description" if lld else "host+description",
        "alert_key_scope": {"type": "host", "name": host, "id": hostid},
        "alert_key_basis_description": familia,
        "alert_key_collision": False, "alert_key_suggested": None, "scope": "zabbix",
        "zabbix": {
            "triggerid": str(indice), "description_raw": f"{familia} #{indice}",
            "description_normalized": familia, "expression_raw": "{1}>0",
            "expression_expanded": f"last(/{host}/item[{indice % 3}])>0",
            "expression_signature": f"last(/{{HOST}}/item[{indice % 3}])>0",
            "recovery_mode": {"value": "0", "name": "expression"},
            "recovery_expression_raw": "", "recovery_expression_expanded": "",
            "priority": {"value": "2", "name": severidade},
            "status": {"value": "0", "name": "enabled"}, "value": {"value": "0", "name": "OK"},
            "state": {"value": "0", "name": "normal"}, "opdata": "", "event_name": "",
            "comments": "", "manual_close": False, "templated": False, "source_template": None,
            "discovered": lld,
            "discovery_rule": {"itemid": "1", "name": "Jobs", "key_": "jobs.disc"} if lld else None,
            "prototype_description": f"{{#NAME}}: {familia}" if lld else None,
            "dependencies": [], "tags": [],
            "host": {"hostid": hostid, "host": host.lower().replace(" ", "-"), "name": host,
                     "status": {"value": "0", "name": "monitored"}, "inventory": {}},
            "host_groups": grupos or ["Servidores"], "templates": [],
            "items": [{"itemid": str(indice), "key_": f"item[{indice % 3}]", "name": "Item",
                       "units": "", "value_type": {"value": "0", "name": "numeric float"},
                       "update_interval": "1m"}],
            "zabbix_version": "7.2.1", "collected_at": "2026-09-05T21:15:09Z",
            "source_hash": f"sha256:{indice:064x}",
        },
    }


def montar_ambiente(base: Path) -> Path:
    """Snapshot com um host dominante e alguns hosts do NOC."""
    alertas: list[dict[str, Any]] = []
    indice = 0

    # O host gigante: 200 alertas em 2 famílias de LLD, num grupo só dele.
    for familia in ("job-ended-not-ok", "job-late"):
        for _ in range(100):
            indice += 1
            alertas.append(_alerta(indice, GIGANTE, "9001", familia, grupos=["Control-M", "Jobs"]))

    # Vizinhos com o mesmo prefixo de nome, mas volume pequeno.
    for posicao, vizinho in enumerate(VIZINHOS):
        for _ in range(5):
            indice += 1
            alertas.append(_alerta(indice, vizinho, f"900{posicao + 2}", "job-ended-not-ok",
                                   grupos=["Control-M"]))

    # Hosts do NOC: 30 alertas, algumas famílias, um host em dois grupos.
    for posicao, host in enumerate(NOC_HOSTS):
        for numero in range(10):
            indice += 1
            alertas.append(_alerta(
                indice, host, f"100{posicao}", ["disk-space", "icmp-loss", "cert-expira"][numero % 3],
                severidade="Disaster" if numero == 0 else "Warning", lld=numero % 2 == 0,
                grupos=["Servidores", "Infraestrutura"] if posicao == 0 else ["Servidores"],
            ))

    snapshot = base / "snapshots" / "20260905_181510"
    (snapshot / "normalized").mkdir(parents=True)
    meta = {
        "collected_at": "2026-09-05T21:15:09Z", "zabbix_version": "7.2.1",
        "scope": {"kind": "environment", "label": "ambiente inteiro",
                  "complete_environment": True, "host_groups": [], "hosts": 6},
        "collection": {"duration_seconds": 58.2, "page_size": 250, "pages": 203,
                       "retries": 0, "batch_reductions": [], "failed_objects": [],
                       "errors": [], "partial": False},
    }
    (snapshot / "normalized" / "alerts.json").write_text(
        json.dumps({"meta": meta, "count": len(alertas), "alerts": alertas}), encoding="utf-8")

    # Duas colisões: uma no host gigante, outra num host do NOC.
    colisoes = [
        {"alert_key": "9001|job-ended-not-ok-1", "strategy": "host+description",
         "reasons": ["expressoes_diferentes"], "distinct_signatures": 2, "distinct_hostids": 1,
         "duplicated_on_hosts": {}, "suggested_key_pattern": "", "suggested_by_trigger": {},
         "suggested_keys": [], "occurrences": [
            {"triggerid": "1", "host": GIGANTE, "hostid": "9001", "host_technical": "control-m-prd-votorantim",
             "description_raw": "job", "items_signature": "", "expression_expanded": "a",
             "expression_signature": "a", "priority": "Warning", "source_template": None}]},
        {"alert_key": "1000|disk-space-1", "strategy": "host+description",
         "reasons": ["expressoes_diferentes"], "distinct_signatures": 2, "distinct_hostids": 1,
         "duplicated_on_hosts": {}, "suggested_key_pattern": "", "suggested_by_trigger": {},
         "suggested_keys": [], "occurrences": [
            {"triggerid": "211", "host": NOC_HOSTS[0], "hostid": "1000", "host_technical": "vibe---zabbix-server",
             "description_raw": "disk", "items_signature": "", "expression_expanded": "b",
             "expression_signature": "b", "priority": "Disaster", "source_template": None}]},
    ]
    (snapshot / "normalized" / "collisions.json").write_text(
        json.dumps({"meta": meta, "count": len(colisoes), "collisions": colisoes}), encoding="utf-8")
    (snapshot / "report.json").write_text(json.dumps({"meta": meta, "counts": {"templates": 0}}), encoding="utf-8")
    return snapshot


ESCOPO_NOC = OperationalScope(id="noc", label="NOC", exclude_hosts=(GIGANTE,))


class BaseEscopo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name)
        cls.snapshot = montar_ambiente(cls.base)
        cls.docs = str(cls.base / "docs")
        Path(cls.docs).mkdir(exist_ok=True)
        cls.todos = ReadModel(cls.snapshot, docs_dir=cls.docs, scope=EVERYTHING)
        cls.noc = ReadModel(cls.snapshot, docs_dir=cls.docs, scope=ESCOPO_NOC)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class TestAmbienteCompletoPreservado(BaseEscopo):
    """O escopo filtra a VISÃO; o snapshot em disco não é tocado."""

    def test_snapshot_continua_com_o_host_excluido(self):
        bruto = json.loads((self.snapshot / "normalized" / "alerts.json").read_text(encoding="utf-8"))
        hosts = {a["zabbix"]["host"]["name"] for a in bruto["alerts"]}
        self.assertIn(GIGANTE, hosts, "o escopo não pode apagar dados do snapshot")
        # 200 do host gigante + 10 dos vizinhos + 30 dos hosts do NOC.
        self.assertEqual(len(bruto["alerts"]), 240)

    def test_escopo_nao_reescreve_o_arquivo(self):
        antes = (self.snapshot / "normalized" / "alerts.json").stat().st_mtime
        ReadModel(self.snapshot, docs_dir=self.docs, scope=ESCOPO_NOC)
        self.assertEqual((self.snapshot / "normalized" / "alerts.json").stat().st_mtime, antes)

    def test_visao_completa_ve_tudo(self):
        self.assertEqual(len(self.todos.alerts), 240)
        self.assertEqual(self.todos.out_of_scope, [])
        self.assertIn(GIGANTE, {h["name"] for h in self.todos.hosts.values()})

    def test_contagem_do_ambiente_independe_do_escopo(self):
        """Os dois modelos precisam concordar sobre o tamanho do ambiente."""
        self.assertEqual(self.noc.environment, self.todos.environment)
        self.assertEqual(self.noc.environment["alerts"], 240)


class TestEscopoNOC(BaseEscopo):
    def test_host_excluido_some_da_visao(self):
        nomes = {h["name"] for h in self.noc.hosts.values()}
        self.assertNotIn(GIGANTE, nomes)
        # 30 dos hosts do NOC + 10 dos vizinhos, que NÃO foram excluídos.
        self.assertEqual(len(self.noc.alerts), 40)
        self.assertEqual(len(self.noc.out_of_scope), 200)
        self.assertEqual(len(self.noc.hosts), 5, "3 hosts do NOC + 2 vizinhos")

    def test_hosts_de_nome_parecido_continuam_no_escopo(self):
        """Excluir 'Control-M PRD' não pode derrubar 'Control-M DEV' por tabela."""
        nomes = {h["name"] for h in self.noc.hosts.values()}
        for vizinho in VIZINHOS:
            self.assertIn(vizinho, nomes, f"{vizinho} não foi excluído explicitamente")

    def test_familias_so_do_host_excluido_desaparecem(self):
        rotulos_noc = {f.label for f in self.noc.families.values()}
        rotulos_todos = {f.label for f in self.todos.families.values()}
        self.assertIn("{#NAME}: job-late", rotulos_todos)
        self.assertNotIn("{#NAME}: job-late", rotulos_noc,
                         "família exclusiva do host fora do escopo não pode aparecer")

    def test_familia_compartilhada_sobrevive_com_menos_alertas(self):
        """`job-ended-not-ok` também existe nos vizinhos: fica, mas encolhe."""
        def total(modelo, rotulo):
            return sum(len(f.alert_ids) for f in modelo.families.values() if f.label == rotulo)

        self.assertEqual(total(self.todos, "{#NAME}: job-ended-not-ok"), 110)
        self.assertEqual(total(self.noc, "{#NAME}: job-ended-not-ok"), 10, "os 100 do gigante saíram")

    def test_host_groups_sao_derivados_dos_hosts_do_escopo(self):
        """Item 10: filtra-se o host; os grupos vêm depois, nunca o contrário."""
        grupos_noc = {g["name"] for g in self.noc.host_groups.values()}
        self.assertNotIn("Jobs", grupos_noc, "grupo só do host excluído some")
        self.assertIn("Control-M", grupos_noc, "o grupo fica: os vizinhos ainda estão nele")
        self.assertIn("Servidores", grupos_noc)

    def test_host_em_dois_grupos_conta_em_cada_um(self):
        grupos = {g["name"]: g for g in self.noc.host_groups.values()}
        self.assertEqual(len(grupos["Infraestrutura"]["host_ids"]), 1)
        self.assertEqual(len(grupos["Servidores"]["host_ids"]), 3)

    def test_colisoes_fora_do_escopo_somem_mas_ficam_no_snapshot(self):
        self.assertEqual(len(self.todos.collisions), 2)
        self.assertEqual(len(self.noc.collisions), 1)
        self.assertEqual(self.noc.collisions[0]["alert_key"], "1000|disk-space-1")
        self.assertEqual(self.noc.collisions_total, 2, "o total do snapshot continua conhecido")

    def test_busca_so_encontra_dentro_do_escopo(self):
        self.assertTrue(self.todos.search_ids("Control-M PRD"))
        self.assertEqual(self.noc.search_ids("Control-M PRD"), [])


class TestMetricasRespeitamOEscopo(BaseEscopo):
    def test_dashboard_do_noc_nao_conta_o_que_esta_fora(self):
        painel = api.dashboard(self.noc, {})
        cards = {c["key"]: c["value"] for c in painel["cards"]}

        completo = {c["key"]: c["value"] for c in api.dashboard(self.todos, {})["cards"]}
        self.assertEqual(cards["alerts"], 40)
        self.assertEqual(cards["hosts"], 5)
        self.assertEqual(cards["families"], len(self.noc.families))
        self.assertLess(cards["alerts"], completo["alerts"])
        self.assertLess(cards["collisions"], completo["collisions"])
        self.assertLess(cards["without_procedure"], completo["without_procedure"])

    def test_dashboard_mostra_as_duas_visoes(self):
        painel = api.dashboard(self.noc, {})
        self.assertEqual(painel["environment"]["alerts"], 240)
        self.assertEqual(painel["environment"]["out_of_scope_alerts"], 200)
        self.assertEqual(painel["environment"]["out_of_scope_hosts"], 1)
        self.assertEqual(painel["scope"]["alerts_in_scope"], 40)
        self.assertEqual(painel["scope"]["label"], "NOC")

    def test_severidades_somam_o_escopo(self):
        painel = api.dashboard(self.noc, {})
        self.assertEqual(sum(s["value"] for s in painel["severities"]), 40)

    def test_familia_gigante_nao_aparece_no_top(self):
        rotulos = {f["label"] for f in api.dashboard(self.noc, {})["top_families"]}
        self.assertNotIn("{#NAME}: job-late", rotulos)

    def test_procedimentos_fora_do_escopo_nao_inflam_o_indicador(self):
        do_noc = {f["status"]: f["value"] for f in api.procedures(self.noc, {})["facets"]["by_status"]}
        de_todos = {f["status"]: f["value"] for f in api.procedures(self.todos, {})["facets"]["by_status"]}
        self.assertLess(do_noc["missing"], de_todos["missing"])
        self.assertEqual(do_noc["missing"], len(self.noc.families))

    def test_listagens_respeitam_o_escopo(self):
        self.assertEqual(api.alerts(self.noc, {})["pagination"]["total"], 40)
        self.assertEqual(api.hosts(self.noc, {})["pagination"]["total"], 5)
        self.assertEqual(api.collisions(self.noc, {})["pagination"]["total"], 1)
        self.assertEqual(api.families(self.noc, {})["pagination"]["total"], len(self.noc.families))

    def test_status_descreve_a_coleta_inteira_e_o_escopo(self):
        class CacheFalso:
            scopes = type("C", (), {"listar": staticmethod(lambda: []), "default_id": "noc"})()
            available_snapshots = staticmethod(lambda: [])

        dados = api.status(self.noc, CacheFalso(), {})
        self.assertEqual(dados["counts"]["alerts"], 240, "status mostra a COLETA, não o escopo")
        self.assertEqual(dados["counts"]["hosts"], 6)
        self.assertEqual(dados["counts"]["collisions"], 2, "colisões do snapshot inteiro")
        self.assertEqual(dados["scope"]["alerts_in_scope"], 40)
        self.assertEqual(dados["environment"]["alerts"], 240)

    def test_busca_avisa_quantos_ficaram_de_fora(self):
        resultado = api.search(self.noc, {"q": ["job"]})
        self.assertGreater(resultado["out_of_scope_alerts"], 0)
        self.assertEqual(resultado["scope"]["id"], "noc")

    def test_troca_de_escopo_muda_os_numeros(self):
        self.assertEqual(api.alerts(self.todos, {})["pagination"]["total"], 240)
        self.assertEqual(api.alerts(self.noc, {})["pagination"]["total"], 40)


class TestConfiguracao(unittest.TestCase):
    def test_exclusao_por_nome_exato_ignora_caixa(self):
        escopo = OperationalScope(id="x", exclude_hosts=("Control-M PRD Votorantim",))
        self.assertFalse(escopo.includes_host("control-m prd votorantim"))
        self.assertTrue(escopo.includes_host("Control-M DEV Votorantim"))

    def test_exclusao_nunca_e_por_substring(self):
        """Excluir um host não pode derrubar outro cujo nome o contenha."""
        escopo = OperationalScope(id="x", exclude_hosts=("Control-M PRD",))
        self.assertTrue(escopo.includes_host("Control-M PRD Votorantim"))

    def test_padrao_com_curinga(self):
        escopo = OperationalScope(id="x", exclude_host_patterns=("Control-M * Votorantim",))
        self.assertFalse(escopo.includes_host("Control-M PRD Votorantim"))
        self.assertFalse(escopo.includes_host("Control-M DEV Votorantim"))
        self.assertTrue(escopo.includes_host("Zabbix server"))

    def test_inclusao_e_lista_fechada(self):
        escopo = OperationalScope(id="x", include_hosts=("Zabbix server",))
        self.assertTrue(escopo.includes_host("Zabbix server"))
        self.assertFalse(escopo.includes_host("Qualquer outro"))

    def test_alerta_sem_host_fica_no_escopo(self):
        """Sumir em silêncio é pior do que aparecer sem endereço."""
        self.assertTrue(OperationalScope(id="x", exclude_hosts=("a",)).includes_host("", ""))

    def test_nome_tecnico_tambem_casa(self):
        escopo = OperationalScope(id="x", exclude_hosts=("control-m-prd",))
        self.assertFalse(escopo.includes_host("Control-M PRD Votorantim", "control-m-prd"))

    def test_sem_arquivo_existe_apenas_o_ambiente_inteiro(self):
        with tempfile.TemporaryDirectory() as tmp:
            configuracao = load_scopes(Path(tmp) / "nao-existe.json")
            self.assertEqual(list(configuracao.scopes), ["all"])
            self.assertTrue(configuracao.get(None).is_everything)

    def test_le_o_scopes_json_do_projeto(self):
        configuracao = load_scopes("scopes.json")
        self.assertIn("noc", configuracao.scopes)
        self.assertEqual(configuracao.default_id, "noc")
        noc = configuracao.get("noc")
        self.assertEqual(noc.mode, "exclude", "o escopo do NOC precisa ser por exclusão")
        self.assertIn(GIGANTE, noc.exclude_hosts)

    def test_escopo_desconhecido_e_erro_claro(self):
        configuracao = parse_scopes({"scopes": [{"id": "noc"}], "default": "noc"})
        with self.assertRaises(ScopeError) as ctx:
            configuracao.get("inexistente")
        self.assertIn("noc", str(ctx.exception))

    def test_all_e_reservado(self):
        with self.assertRaises(ScopeError):
            parse_scopes({"scopes": [{"id": "all"}]})

    def test_misturar_inclusao_e_exclusao_e_recusado(self):
        with self.assertRaises(ScopeError):
            parse_scopes({"scopes": [{"id": "x", "include_hosts": ["a"], "exclude_hosts": ["b"]}]})

    def test_default_inexistente_e_recusado(self):
        with self.assertRaises(ScopeError):
            parse_scopes({"scopes": [{"id": "noc"}], "default": "outro"})

    def test_campo_com_tipo_errado_e_recusado(self):
        with self.assertRaises(ScopeError):
            parse_scopes({"scopes": [{"id": "x", "exclude_hosts": "um texto"}]})


if __name__ == "__main__":
    unittest.main()
