"""Regras operacionais: agrupamento, instâncias, confiança e decisão.

O cenário reproduz o host real `Vibe - MSTracker-vm Hom`, onde 36 alertas se
espalham por 29 famílias técnicas — e onde cinco delas (espaço, inodes,
read-only, e a mesma coisa escrita em português) são obviamente a mesma unidade
de documentação.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.rules.candidates import HIGH, LOW, MEDIUM, build_candidates
from src.rules.decisions import CANDIDATE, CONFIRMED, IGNORED, SPLIT, DecisionError, DecisionStore
from src.rules.instances import from_item_keys, from_prototype, instance_of
from src.rules.taxonomy import UNCATEGORIZED, classify


def alerta(triggerid: str, descricao: str, chaves: list[str], *, host: str = "MSTracker",
           hostid: str = "1001", grupos: list[str] | None = None, severidade: str = "Warning",
           prototipo: str | None = None, dependencias: list[str] | None = None) -> dict[str, Any]:
    return {
        "alert_key": f"{hostid}|{triggerid}", "alert_key_strategy": "host+description",
        "alert_key_scope": {"type": "host", "name": host, "id": hostid},
        "alert_key_basis_description": descricao, "alert_key_collision": False,
        "alert_key_suggested": None, "scope": "zabbix",
        "zabbix": {
            "triggerid": triggerid, "description_raw": descricao,
            "description_normalized": descricao.lower(), "expression_raw": "{1}>0",
            "expression_expanded": f"last(/{host}/{chaves[0] if chaves else 'x'})>0",
            "expression_signature": "sig", "recovery_mode": {"value": "0", "name": "expression"},
            "recovery_expression_raw": "", "recovery_expression_expanded": "",
            "priority": {"value": "2", "name": severidade},
            "status": {"value": "0", "name": "enabled"}, "value": {"value": "0", "name": "OK"},
            "state": {"value": "0", "name": "normal"}, "opdata": "", "event_name": "",
            "comments": "", "manual_close": False, "templated": False, "source_template": None,
            "discovered": prototipo is not None,
            "discovery_rule": {"itemid": "1", "name": "Discovery", "key_": "disc"} if prototipo else None,
            "prototype_description": prototipo,
            "dependencies": [{"triggerid": d, "description": "dep", "host": host}
                             for d in (dependencias or [])],
            "tags": [],
            "host": {"hostid": hostid, "host": host.lower(), "name": host,
                     "status": {"value": "0", "name": "monitored"}, "inventory": {}},
            "host_groups": grupos or ["Vibe Tecnologia"], "templates": [],
            "items": [{"itemid": f"{triggerid}-{i}", "key_": c, "name": c, "units": "",
                       "value_type": {"value": "0", "name": "numeric float"}, "update_interval": "1m"}
                      for i, c in enumerate(chaves)],
            "zabbix_version": "7.2.1", "collected_at": "2026-09-05T21:15:09Z",
            "source_hash": f"sha256:{triggerid}",
        },
    }


#: O caso real: 5 descrições diferentes, 1 unidade operacional.
DISCO = [
    alerta("1", "/: Disk space is critically low", ["vfs.fs.dependent.size[/,pused]"],
           prototipo="{#FSNAME}: Disk space is critically low"),
    alerta("2", "/: Disk space is low", ["vfs.fs.dependent.size[/,pused]"], dependencias=["1"],
           prototipo="{#FSNAME}: Disk space is low"),
    alerta("3", "/: Running out of free inodes", ["vfs.fs.dependent.inode[/,pfree]"],
           prototipo="{#FSNAME}: Running out of free inodes"),
    alerta("4", "/: Filesystem has become read-only", ["vfs.fs.dependent[/,readonly]"],
           prototipo="{#FSNAME}: Filesystem has become read-only"),
    # Em português: nenhuma palavra em comum com as outras. Só a chave do
    # item as coloca no mesmo lugar.
    alerta("5", "/boot: Pouco espaço em disco", ["vfs.fs.dependent.size[/boot,pused]"],
           prototipo="{#FSNAME}: Pouco espaço em disco"),
]

#: Duas descrições sem palavra em comum, mesma unidade operacional.
CPU = [
    alerta("10", "Linux: High CPU utilization", ["system.cpu.util"]),
    alerta("11", "Linux: Load average is too high", ["system.cpu.load", "system.cpu.num"]),
]

REDE = [
    alerta("20", "Interface ens160: Link down", ["net.if.in[ens160]"],
           prototipo="Interface {#IFNAME}: Link down"),
    alerta("21", "Interface ens160: High bandwidth usage", ["net.if.out[ens160]"],
           prototipo="Interface {#IFNAME}: High bandwidth usage"),
    alerta("22", "Interface eth0: Link down", ["net.if.in[eth0]"],
           prototipo="Interface {#IFNAME}: Link down"),
]

TODOS = DISCO + CPU + REDE


class TestTaxonomia(unittest.TestCase):
    def test_chave_de_item_agrupa_o_que_a_descricao_espalharia(self):
        categorias = {classify(a).category_id for a in DISCO}
        self.assertEqual(categorias, {"filesystem"},
                         "5 descrições diferentes, inclusive em português, viram uma categoria")

    def test_cpu_e_load_average_ficam_juntos(self):
        """Duas descrições sem nenhuma palavra em comum."""
        self.assertEqual({classify(a).category_id for a in CPU}, {"cpu"})

    def test_dois_sinais_dao_confianca(self):
        resultado = classify(DISCO[0])
        self.assertTrue(resultado.by_item)
        self.assertTrue(resultado.by_keyword)
        self.assertTrue(resultado.confident)
        self.assertEqual(len(resultado.evidence), 2)

    def test_chave_de_item_prevalece_sobre_a_descricao(self):
        """Quando os dois sinais discordam, o estrutural vence — e diz por quê."""
        conflitante = alerta("99", "Alta utilização de CPU no volume", ["vfs.fs.size[/,pused]"])
        resultado = classify(conflitante)
        self.assertEqual(resultado.category_id, "filesystem")
        self.assertTrue(resultado.by_item)
        self.assertTrue(any("prevalece" in e for e in resultado.evidence),
                        "a discordância precisa aparecer na evidência, não sumir")

    def test_chave_desconhecida_deixa_a_descricao_decidir(self):
        """`Interface X` lido de um item calculado: a chave não sabe, a descrição sim."""
        calculado = alerta("97", "Interface ens160: Link down", ["vfs.file.contents[/tmp/x]"])
        resultado = classify(calculado)
        self.assertEqual(resultado.category_id, "network_interface")
        self.assertTrue(resultado.by_keyword)
        self.assertFalse(resultado.confident, "um sinal só não dá confiança alta")

    def test_sem_sinal_nenhum_fica_sem_categoria(self):
        """Inventar um agrupamento é pior do que admitir que não sabemos."""
        obscuro = alerta("98", "Coisa esquisita aconteceu", ["algo.desconhecido.xyz"])
        self.assertEqual(classify(obscuro).category_id, UNCATEGORIZED)

    def test_alerta_sem_categoria_nao_entra_em_regra(self):
        obscuro = alerta("98", "Coisa esquisita", ["algo.desconhecido.xyz"])
        candidatos = build_candidates([*DISCO, obscuro])
        dentro = {t for c in candidatos.values() for t in c.alert_ids}
        self.assertNotIn("98", dentro)


class TestInstancias(unittest.TestCase):
    def test_extrai_do_prototipo(self):
        self.assertEqual(
            from_prototype("{#FSNAME}: Disk space is low", "/boot: Disk space is low"), ["/boot"])

    def test_extrai_varias_macros(self):
        valores = from_prototype("Interface {#IFNAME}({#IFALIAS}): erro", "Interface ens160(uplink): erro")
        self.assertEqual(valores, ["ens160", "uplink"])

    def test_macro_nao_expandida_nao_e_instancia(self):
        """`{#FSLABEL}` é a forma, não a entidade — apareceu no ambiente real."""
        self.assertEqual(from_prototype("{#FSLABEL}: cheio", "{#FSLABEL}: cheio"), [])

    def test_prototipo_que_nao_casa_nao_inventa(self):
        self.assertEqual(from_prototype("{#FSNAME}: disco", "outra coisa totalmente"), [])

    def test_fallback_por_chave_de_item(self):
        self.assertEqual(from_item_keys(alerta("1", "x", ["vfs.fs.size[/boot,pused]"])), ["/boot"])

    def test_modo_do_item_nao_vira_instancia(self):
        """Sem isto, `pused` viraria uma instância chamada 'pused'."""
        self.assertNotIn("pused", from_item_keys(alerta("1", "x", ["vfs.fs.size[/boot,pused]"])))

    def test_origem_da_instancia_e_declarada(self):
        """Quem lê precisa saber se veio do protótipo (exato) ou da chave (inferido)."""
        self.assertEqual(instance_of(DISCO[0])["source"], "prototype")
        por_chave = instance_of(alerta("1", "x", ["vfs.fs.size[/var,pused]"]))
        self.assertEqual(por_chave["source"], "item_key")
        self.assertEqual(por_chave["name"], "/var")

    def test_sem_instancia_e_estado_valido(self):
        """Muita regra se aplica ao host inteiro."""
        self.assertIsNone(instance_of(alerta("1", "Zabbix agent down", ["zabbix[host,agent]"])),
                          "`host` e `agent` são termos genéricos, não entidades descobertas")
        self.assertIsNone(instance_of(alerta("2", "Linux: High CPU utilization", ["system.cpu.util"])))


class TestCandidatos(unittest.TestCase):
    def setUp(self):
        self.candidatos = build_candidates(TODOS)
        self.disco = self.candidatos["vibe-tecnologia--filesystem"]

    def test_familias_diferentes_viram_uma_regra(self):
        """O ponto inteiro da Fase 4: 5 famílias técnicas, 1 unidade."""
        self.assertEqual(len(self.disco.alert_ids), 5)
        self.assertEqual(sorted(self.disco.instances), ["/", "/boot"])

    def test_lld_nao_gera_uma_regra_por_instancia(self):
        """3 alertas de interface em 2 instâncias = 1 regra, não 2 nem 3."""
        rede = self.candidatos["vibe-tecnologia--network_interface"]
        self.assertEqual(len(rede.alert_ids), 3)
        self.assertEqual(sorted(rede.instances), ["ens160", "eth0"])
        regras_de_rede = [c for c in self.candidatos.values() if c.category_id == "network_interface"]
        self.assertEqual(len(regras_de_rede), 1)

    def test_dependencia_entre_triggers_conta(self):
        self.assertEqual(self.disco.dependencies_internal, 1)
        _, motivos = self.disco.confidence()
        self.assertTrue(any("dependência" in m for m in motivos))

    def test_dependencia_para_fora_da_regra_nao_conta(self):
        externo = alerta("30", "Linux: High CPU utilization", ["system.cpu.util"], dependencias=["1"])
        candidatos = build_candidates([*DISCO, externo])
        self.assertEqual(candidatos["vibe-tecnologia--cpu"].dependencies_internal, 0)

    def test_confianca_alta_com_varios_sinais(self):
        nivel, motivos = self.disco.confidence()
        self.assertEqual(nivel, HIGH)
        self.assertTrue(motivos)

    def test_confianca_baixa_em_agrupamento_pequeno_e_fraco(self):
        """Um alerta só, classificado apenas pela descrição."""
        fraco = alerta("40", "Alguma coisa com certificado", ["desconhecido.xyz"])
        candidatos = build_candidates([fraco])
        nivel, motivos = next(iter(candidatos.values())).confidence()
        self.assertEqual(nivel, LOW)
        self.assertTrue(any("⚠" in m for m in motivos), "o motivo precisa dizer o que enfraqueceu")

    def test_confianca_media_entre_os_extremos(self):
        medios = [alerta(str(50 + i), "Linux: High memory utilization", ["vm.memory.utilization"])
                  for i in range(4)]
        nivel, _ = build_candidates(medios)["vibe-tecnologia--memory"].confidence()
        self.assertIn(nivel, (MEDIUM, HIGH))

    def test_todo_candidato_explica_por_que(self):
        """Item 27: um agrupamento inexplicável não deveria ser confirmado."""
        for candidato in self.candidatos.values():
            _, motivos = candidato.confidence()
            self.assertTrue(motivos, f"{candidato.id} não explica o agrupamento")

    def test_host_em_dois_grupos_aparece_nos_dois(self):
        multi = alerta("60", "/: Disk space is low", ["vfs.fs.size[/,pused]"],
                       grupos=["Vibe Tecnologia", "Servidores"])
        candidatos = build_candidates([multi])
        self.assertIn("vibe-tecnologia--filesystem", candidatos)
        self.assertIn("servidores--filesystem", candidatos)

    def test_regra_reune_varias_familias_tecnicas(self):
        familias = {t: f"fam-{t}" for t in ("1", "2", "3", "4", "5")}
        candidatos = build_candidates(DISCO, familias)
        self.assertEqual(len(candidatos["vibe-tecnologia--filesystem"].family_ids), 5)

    def test_payload_diz_possivel_e_nao_afirma(self):
        payload = self.disco.to_dict()
        self.assertEqual(payload["status"], "candidate")
        self.assertIn(payload["confidence"], (HIGH, MEDIUM, LOW))
        self.assertTrue(payload["reasons"])


class TestDecisoes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = DecisionStore(Path(self._tmp.name) / "rule_decisions.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_candidato_vira_confirmado(self):
        self.store.set("grupo--filesystem", CONFIRMED, by="operador")
        registro = self.store.get("grupo--filesystem")
        self.assertEqual(registro["status"], CONFIRMED)
        self.assertEqual(registro["decided_by"], "operador")
        self.assertTrue(registro["decided_at"])

    def test_candidato_vira_ignorado(self):
        self.store.set("grupo--cpu", IGNORED, note="ruído conhecido")
        self.assertEqual(self.store.get("grupo--cpu")["status"], IGNORED)
        self.assertEqual(self.store.get("grupo--cpu")["note"], "ruído conhecido")

    def test_manter_separado(self):
        self.store.set("grupo--rede", SPLIT)
        self.assertEqual(self.store.get("grupo--rede")["status"], SPLIT)

    def test_desfazer_volta_para_candidato(self):
        self.store.set("grupo--cpu", CONFIRMED)
        self.store.set("grupo--cpu", CANDIDATE)
        self.assertIsNone(self.store.get("grupo--cpu"), "desfazer apaga a decisão")

    def test_decisao_invalida_e_recusada(self):
        with self.assertRaises(DecisionError):
            self.store.set("grupo--x", "talvez")

    def test_decisao_sobrevive_a_releitura(self):
        self.store.set("grupo--filesystem", CONFIRMED)
        outro = DecisionStore(self.store.path)
        self.assertEqual(outro.get("grupo--filesystem")["status"], CONFIRMED)

    def test_arquivo_ausente_nao_quebra(self):
        vazio = DecisionStore(Path(self._tmp.name) / "nao-existe.json")
        self.assertEqual(vazio.all(), {})
        self.assertIsNone(vazio.get("qualquer"))

    def test_contagem_por_estado(self):
        self.store.set("a", CONFIRMED)
        self.store.set("b", CONFIRMED)
        self.store.set("c", IGNORED)
        self.assertEqual(self.store.counts()[CONFIRMED], 2)
        self.assertEqual(self.store.counts()[IGNORED], 1)


class TestEscala(unittest.TestCase):
    """Item 35: 19k alertas, com uma família de 8k."""

    def test_familia_gigante_vira_uma_regra_com_muitas_instancias(self):
        gigante = [
            alerta(str(1000 + i), f"CTMSERVER:{i:05d} - Job: X - Ended Not Ok",
                   [f"job.status[{i}]"], host="Control-M PRD", hostid="9001",
                   grupos=["Control-M"], prototipo="{#JOBID} - Job: X - Ended Not Ok")
            for i in range(8131)
        ]
        candidatos = build_candidates(gigante)
        regras = [c for c in candidatos.values() if c.category_id == "job"]

        self.assertEqual(len(regras), 1, "8.131 alertas = UMA regra, não 8.131 documentações")
        self.assertEqual(len(regras[0].alert_ids), 8131)
        self.assertEqual(len(regras[0].instances), 8131, "cada job é uma instância")

    def test_volume_realista_termina_rapido(self):
        import time

        alertas = []
        for h in range(78):
            for n in range(33):
                alertas.append(alerta(
                    f"{h}-{n}",
                    ["/: Disk space is low", "Linux: High CPU utilization",
                     "Interface ens160: Link down", "Zabbix agent is not available"][n % 4],
                    [["vfs.fs.size[/,pused]", "system.cpu.util", "net.if.in[ens160]",
                      "zabbix[host,agent]"][n % 4]],
                    host=f"Host {h}", hostid=f"10{h:03d}", grupos=[f"Grupo {h % 21}"]))

        inicio = time.monotonic()
        candidatos = build_candidates(alertas)
        duracao = time.monotonic() - inicio

        self.assertLess(duracao, 10.0, f"agrupamento levou {duracao:.1f}s")
        self.assertGreater(len(candidatos), 10)
        self.assertLess(len(candidatos), len(alertas) / 10,
                        "o objetivo é reduzir drasticamente as unidades de documentação")


if __name__ == "__main__":
    unittest.main()
