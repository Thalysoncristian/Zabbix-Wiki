"""Modelo da ficha, máquina de estados e persistência."""

import json
import tempfile
import unittest
from pathlib import Path

from src.core.models import (
    LEVEL_FAMILY,
    LEVEL_OVERRIDE,
    SCOPE_MANUAL,
    AlertDoc,
    alert_key_to_filename,
    empty_operational,
)
from src.core.repository import AlertRepository, ConcurrentModificationError
from src.core.status import (
    DOCUMENTED,
    NOT_APPLICABLE,
    REVIEW_NEEDED,
    REVIEWED,
    UNDOCUMENTED,
    StatusError,
    assert_can_document,
    assert_transition,
    can_transition,
    missing_fields_for_documented,
)


class TestNomeDeArquivo(unittest.TestCase):
    def test_separador_da_chave_vira_nome_valido_no_windows(self):
        nome = alert_key_to_filename("vibe-wazuh-siem|running-out-of-free-inodes")
        self.assertEqual(nome, "vibe-wazuh-siem__running-out-of-free-inodes.json")
        for proibido in '<>:"/\\|?*':
            self.assertNotIn(proibido, nome)

    def test_chave_longa_e_truncada_mas_continua_unica(self):
        base = "atualiza|" + "a" * 300
        outra = "atualiza|" + "a" * 299 + "b"
        self.assertNotEqual(alert_key_to_filename(base), alert_key_to_filename(outra))
        self.assertLess(len(alert_key_to_filename(base)), 130)

    def test_deterministico(self):
        chave = "srv-01|disco-cheio"
        self.assertEqual(alert_key_to_filename(chave), alert_key_to_filename(chave))

    def test_nome_reservado_do_windows_e_escapado(self):
        self.assertTrue(alert_key_to_filename("con").startswith("_"))
        self.assertTrue(alert_key_to_filename("LPT1").startswith("_"))


class TestMaquinaDeEstados(unittest.TestCase):
    def test_fluxo_principal(self):
        self.assertTrue(can_transition(UNDOCUMENTED, DOCUMENTED))
        self.assertTrue(can_transition(DOCUMENTED, REVIEWED))
        self.assertTrue(can_transition(DOCUMENTED, REVIEW_NEEDED))
        self.assertTrue(can_transition(REVIEWED, REVIEW_NEEDED))

    def test_nao_pula_de_undocumented_para_reviewed(self):
        self.assertFalse(can_transition(UNDOCUMENTED, REVIEWED))
        with self.assertRaises(StatusError):
            assert_transition(UNDOCUMENTED, REVIEWED)

    def test_status_inexistente_e_recusado(self):
        with self.assertRaises(StatusError):
            assert_transition(DOCUMENTED, "inventado")

    def test_not_applicable_alcancavel_de_qualquer_estado(self):
        for estado in (UNDOCUMENTED, DOCUMENTED, REVIEWED, REVIEW_NEEDED):
            self.assertTrue(can_transition(estado, NOT_APPLICABLE), estado)

    def test_campos_minimos_impedem_documentar_um_rascunho(self):
        vazio = empty_operational()
        faltando = missing_fields_for_documented(vazio)
        self.assertIn("meaning (o que o alerta significa)", faltando)
        with self.assertRaises(StatusError):
            assert_can_document(vazio)

    def test_chamado_exige_equipe_e_fila(self):
        parcial = {**empty_operational(), "meaning": "x", "resolution_criteria": "y", "requires_ticket": True}
        faltando = missing_fields_for_documented(parcial)
        self.assertTrue(any("routing.team" in f for f in faltando))
        self.assertTrue(any("routing.ticket_queue" in f for f in faltando))

    def test_alerta_que_nao_abre_chamado_nao_exige_roteamento(self):
        completo = {**empty_operational(), "meaning": "x", "resolution_criteria": "y", "requires_ticket": False}
        self.assertEqual(missing_fields_for_documented(completo), [])
        assert_can_document(completo)


class TestFicha(unittest.TestCase):
    def test_ficha_nasce_undocumented_com_operacional_vazio(self):
        doc = AlertDoc(alert_key="srv|x")
        self.assertEqual(doc.doc_status, UNDOCUMENTED)
        self.assertEqual(doc.doc_level, LEVEL_FAMILY)
        self.assertIsNone(doc.ai_suggestion)

    def test_override_e_criado_por_humano_e_aponta_para_a_familia(self):
        doc = AlertDoc.override("srv-01|disk-space-low", family_key="lld|srv-01|vfs|fsname-disk-space-low")
        self.assertEqual(doc.doc_level, LEVEL_OVERRIDE)
        self.assertTrue(doc.alert_key.startswith("override|"))
        self.assertEqual(doc.family_key, "lld|srv-01|vfs|fsname-disk-space-low")

    def test_ficha_manual_nao_tem_bloco_zabbix(self):
        doc = AlertDoc.manual("pagamento-nao-processado")
        self.assertEqual(doc.scope, SCOPE_MANUAL)
        self.assertIsNone(doc.zabbix)
        self.assertFalse(doc.present_in_zabbix)

    def test_serializacao_preserva_os_tres_blocos(self):
        doc = AlertDoc(alert_key="srv|x", zabbix={"triggerid": "1"}, ai_suggestion={"suggested_team": "Infra"})
        payload = doc.to_dict()
        for bloco in ("zabbix", "ai_suggestion", "operational"):
            self.assertIn(bloco, payload)
        recuperado = AlertDoc.from_dict(payload)
        self.assertEqual(recuperado.zabbix, {"triggerid": "1"})
        self.assertEqual(recuperado.ai_suggestion, {"suggested_team": "Infra"})

    def test_status_invalido_no_arquivo_cai_para_undocumented(self):
        doc = AlertDoc.from_dict({"alert_key": "x", "operational": {"doc_status": "qualquer-coisa"}})
        self.assertEqual(doc.doc_status, UNDOCUMENTED)

    def test_touch_avanca_a_revisao(self):
        doc = AlertDoc(alert_key="srv|x")
        anterior = doc.revision
        doc.touch()
        self.assertEqual(doc.revision, anterior + 1)


class TestRepositorio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = AlertRepository(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_ida_e_volta(self):
        doc = AlertDoc.manual("pagamento|nao-processado")
        doc.operational["meaning"] = "Pagamento não processou"
        self.repo.save(doc)
        lido = self.repo.get("pagamento|nao-processado")
        self.assertEqual(lido.operational["meaning"], "Pagamento não processou")

    def test_json_gravado_e_legivel_e_com_acento(self):
        doc = AlertDoc.manual("x")
        doc.operational["meaning"] = "Partição raiz acima do limite"
        caminho = self.repo.save(doc)
        conteudo = caminho.read_text(encoding="utf-8")
        self.assertIn("Partição raiz", conteudo, "não deve escapar acentos em \\u")
        json.loads(conteudo)

    def test_edicao_concorrente_e_recusada(self):
        self.repo.save(AlertDoc.manual("ficha"))
        pessoa_a = self.repo.get("ficha")
        pessoa_b = self.repo.get("ficha")

        pessoa_b.operational["meaning"] = "editado às 03:02"
        pessoa_b.touch()
        self.repo.save(pessoa_b, expected_revision=pessoa_b.revision - 1)

        pessoa_a.operational["meaning"] = "editado às 03:00, salvo depois"
        pessoa_a.touch()
        with self.assertRaises(ConcurrentModificationError):
            self.repo.save(pessoa_a, expected_revision=0)

        self.assertEqual(self.repo.get("ficha").operational["meaning"], "editado às 03:02")

    def test_arquivo_corrompido_e_ignorado_sem_derrubar_a_leitura(self):
        self.repo.save(AlertDoc.manual("boa"))
        (Path(self.tmp.name) / "quebrada.json").write_text("{isso não é json", encoding="utf-8")
        chaves = [d.alert_key for d in self.repo.all()]
        self.assertEqual(chaves, ["boa"])


if __name__ == "__main__":
    unittest.main()
