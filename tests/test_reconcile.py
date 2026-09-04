"""Reconciliação: as garantias que protegem a documentação humana."""

import tempfile
import unittest
from pathlib import Path

from src.core.models import LEVEL_FAMILY, LEVEL_INSTANCE, AlertDoc, build_family_key
from src.core.repository import AlertRepository
from src.core.status import DOCUMENTED, REVIEW_NEEDED, REVIEWED, UNDOCUMENTED
from src.reconcile import reconcile


def _alerta(alert_key, triggerid, *, source_hash="sha256:aaa", host="srv-01", hostid="1",
            desc="Disk space low", lld=None, grupos=("Infraestrutura",)):
    zbx = {
        "triggerid": triggerid,
        "description_raw": desc,
        "description_normalized": desc.lower().replace(" ", "-"),
        "expression_signature": "last(/{HOST}/vfs.fs.size)<20",
        "source_hash": source_hash,
        "collected_at": "2026-09-04T12:00:00Z",
        "host": {"host": host, "name": host, "hostid": hostid},
        "host_groups": list(grupos),
        "discovered": bool(lld),
        "prototype_description": lld[1] if lld else None,
        "discovery_rule": {"key_": lld[0], "name": lld[0]} if lld else None,
    }
    return {"alert_key": alert_key, "alert_key_scope": {"type": "host", "name": host, "id": hostid},
            "alert_key_strategy": "host+description", "zabbix": zbx}


def _documentar(repo, chave, status=DOCUMENTED):
    doc = repo.get(chave)
    doc.operational.update({
        "doc_status": status,
        "meaning": "Partição raiz acima do limite",
        "requires_ticket": True,
        "resolution_criteria": "Uso abaixo de 80%",
        "routing": {"team": "Infraestrutura", "ticket_queue": "N2", "ticket_category": "",
                    "ticket_subcategory": "", "channel": "DeskManager"},
    })
    doc.touch()
    repo.save(doc)
    return doc


class TestReconcile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = AlertRepository(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_alerta_novo_vira_ficha_undocumented(self):
        resultado = reconcile([_alerta("srv-01|disk-space-low", "100")], self.repo)
        self.assertEqual(resultado.summary()["created"], 1)
        doc = self.repo.get("srv-01|disk-space-low")
        self.assertEqual(doc.doc_status, UNDOCUMENTED)
        self.assertEqual(doc.scope, "zabbix")
        self.assertIsNotNone(doc.zabbix)

    def test_segunda_coleta_identica_nao_muda_nada(self):
        alertas = [_alerta("srv-01|disk-space-low", "100")]
        reconcile(alertas, self.repo)
        resultado = reconcile(alertas, self.repo)
        self.assertEqual(resultado.summary()["created"], 0)
        self.assertEqual(resultado.summary()["unchanged"], 1)
        self.assertEqual(resultado.summary()["marked_review_needed"], 0)

    def test_mudanca_tecnica_marca_review_needed_sem_apagar_documentacao(self):
        reconcile([_alerta("srv-01|disk-space-low", "100", source_hash="sha256:antigo")], self.repo)
        _documentar(self.repo, "srv-01|disk-space-low")

        reconcile([_alerta("srv-01|disk-space-low", "100", source_hash="sha256:novo")], self.repo)

        doc = self.repo.get("srv-01|disk-space-low")
        self.assertEqual(doc.doc_status, REVIEW_NEEDED)
        self.assertEqual(doc.operational["meaning"], "Partição raiz acima do limite", "documentação foi perdida")
        self.assertEqual(doc.operational["routing"]["team"], "Infraestrutura")

    def test_trigger_recriado_com_novo_id_preserva_a_documentacao(self):
        # triggerid não é identidade: o Zabbix recriou o trigger, a ficha continua.
        reconcile([_alerta("srv-01|disk-space-low", "100")], self.repo)
        _documentar(self.repo, "srv-01|disk-space-low", status=REVIEWED)

        reconcile([_alerta("srv-01|disk-space-low", "999999")], self.repo)

        doc = self.repo.get("srv-01|disk-space-low")
        self.assertEqual(doc.zabbix["triggerid"], "999999", "o fato técnico deve ser atualizado")
        self.assertEqual(doc.operational["meaning"], "Partição raiz acima do limite")
        self.assertEqual(doc.doc_status, REVIEWED, "mesmo hash técnico: não precisa de nova revisão")

    def test_edicao_humana_nunca_dispara_review_needed(self):
        reconcile([_alerta("srv-01|disk-space-low", "100")], self.repo)
        _documentar(self.repo, "srv-01|disk-space-low")
        reconcile([_alerta("srv-01|disk-space-low", "100")], self.repo)
        self.assertEqual(self.repo.get("srv-01|disk-space-low").doc_status, DOCUMENTED)

    def test_alerta_que_some_preserva_a_ficha(self):
        reconcile([_alerta("srv-01|disk-space-low", "100")], self.repo)
        _documentar(self.repo, "srv-01|disk-space-low")

        resultado = reconcile([_alerta("srv-02|outro-alerta", "200", host="srv-02", hostid="2")], self.repo)

        self.assertEqual(resultado.summary()["disappeared"], 1)
        doc = self.repo.get("srv-01|disk-space-low")
        self.assertIsNotNone(doc, "a ficha não pode ser apagada")
        self.assertFalse(doc.present_in_zabbix)
        self.assertEqual(doc.operational["meaning"], "Partição raiz acima do limite")

    def test_alerta_que_volta_e_remarcado_como_presente(self):
        alerta = _alerta("srv-01|disk-space-low", "100")
        reconcile([alerta], self.repo)
        reconcile([_alerta("srv-02|outro", "200", host="srv-02", hostid="2")], self.repo)
        resultado = reconcile([alerta], self.repo)
        self.assertEqual(resultado.summary()["reappeared"], 1)
        self.assertTrue(self.repo.get("srv-01|disk-space-low").present_in_zabbix)

    def test_coleta_por_grupo_nao_marca_fichas_de_outro_grupo_como_ausentes(self):
        # O fluxo real: coletar grupo a grupo. Fichas fora do escopo da coleta
        # não sumiram — elas nem estavam sendo procuradas.
        reconcile([_alerta("srv-01|alerta-a", "100", grupos=("Servidores",))], self.repo,
                  scope_host_groups=["Servidores"])
        resultado = reconcile([_alerta("net-01|alerta-b", "200", host="net-01", hostid="2",
                                       desc="Interface down", grupos=("Ativos de Rede",))],
                              self.repo, scope_host_groups=["Ativos de Rede"])

        self.assertEqual(resultado.summary()["disappeared"], 0)
        self.assertTrue(self.repo.get("srv-01|alerta-a").present_in_zabbix)


class TestNivelDaFicha(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = AlertRepository(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_familia_de_lld_vira_uma_unica_ficha(self):
        # 5 serviços descobertos no mesmo protótipo = 1 procedimento, 1 ficha.
        alertas = [
            _alerta(f"srv-01|{svc}-nao-esta-rodando", str(i), desc=f'"{svc}" is not running',
                    lld=("service.discovery", '"{#SERVICE.NAME}" is not running'))
            for i, svc in enumerate(("AudioSrv", "BFE", "Spooler", "W32Time", "SSMAgent"), start=1)
        ]
        resultado = reconcile(alertas, self.repo)

        self.assertEqual(resultado.summary()["created"], 1, "5 serviços deveriam gerar 1 ficha de família")
        doc = next(self.repo.all())
        self.assertEqual(doc.doc_level, LEVEL_FAMILY)
        self.assertEqual(len(doc.instances), 5, "as instâncias ficam listadas na ficha")
        self.assertTrue(doc.alert_key.startswith("family:lld|"))

    def test_alerta_unico_da_familia_vira_ficha_de_instancia(self):
        reconcile([_alerta("srv-01|disk-space-low", "100")], self.repo)
        doc = next(self.repo.all())
        self.assertEqual(doc.doc_level, LEVEL_INSTANCE)
        self.assertEqual(doc.alert_key, "srv-01|disk-space-low")

    def test_documentar_a_familia_cobre_instancias_futuras(self):
        base = [
            _alerta(f"srv-01|{svc}", str(i), desc=f'"{svc}" is not running',
                    lld=("service.discovery", '"{#SERVICE.NAME}" is not running'))
            for i, svc in enumerate(("AudioSrv", "BFE"), start=1)
        ]
        reconcile(base, self.repo)
        chave_familia = next(self.repo.all()).alert_key
        _documentar(self.repo, chave_familia)

        # Um serviço novo é descoberto: já nasce coberto pelo procedimento.
        novo = base + [_alerta("srv-01|Spooler", "3", desc='"Spooler" is not running',
                               lld=("service.discovery", '"{#SERVICE.NAME}" is not running'))]
        resultado = reconcile(novo, self.repo)

        self.assertEqual(resultado.summary()["created"], 0, "não deveria criar ficha para o serviço novo")
        doc = self.repo.get(chave_familia)
        self.assertEqual(doc.doc_status, DOCUMENTED)
        self.assertEqual(len(doc.instances), 3)

    def test_familias_diferentes_nao_se_misturam(self):
        servicos = _alerta("srv-01|audiosrv", "1", desc='"AudioSrv" is not running',
                           lld=("service.discovery", '"{#SERVICE.NAME}" is not running'))
        discos = _alerta("srv-01|var", "2", desc="/var: Disk space low",
                         lld=("vfs.fs.discovery", "{#FSNAME}: Disk space low"))
        self.assertNotEqual(build_family_key(servicos), build_family_key(discos))


class TestHashDeFamilia(unittest.TestCase):
    """A ficha de família não pode pedir revisão quando as instâncias trocam."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = AlertRepository(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def _servico(nome, triggerid, prioridade="3"):
        alerta = _alerta(f"win|{nome}", triggerid, source_hash=f"sha256:instancia-{triggerid}",
                         host="Windows bob", hostid="1", desc=f'"{nome}" is not running',
                         lld=("service.discovery", '"{#SERVICE.NAME}" is not running'))
        alerta["zabbix"]["priority"] = {"value": prioridade, "name": "Average"}
        alerta["zabbix"]["recovery_mode"] = {"value": "0"}
        alerta["zabbix"]["manual_close"] = False
        alerta["zabbix"]["tags"] = []
        alerta["zabbix"]["templates"] = []
        alerta["zabbix"]["items"] = []
        return alerta

    def _documentar_familia(self):
        chave = next(self.repo.all()).alert_key
        _documentar(self.repo, chave)
        return chave

    def test_instancias_novas_e_removidas_nao_pedem_revisao(self):
        # Um chamado fecha, dois serviços novos são descobertos: o procedimento
        # da família é exatamente o mesmo.
        self.repo and reconcile([self._servico("AudioSrv", "1"), self._servico("BFE", "2")], self.repo)
        chave = self._documentar_familia()

        resultado = reconcile(
            [self._servico("BFE", "2"), self._servico("Spooler", "3"), self._servico("W32Time", "4")], self.repo
        )

        doc = self.repo.get(chave)
        self.assertEqual(doc.doc_status, DOCUMENTED, "trocar instâncias não é mudança de procedimento")
        self.assertEqual(resultado.summary()["marked_review_needed"], 0)
        self.assertEqual(len(doc.instances), 3)

    def test_mudanca_na_regra_da_familia_pede_revisao(self):
        reconcile([self._servico("AudioSrv", "1"), self._servico("BFE", "2")], self.repo)
        chave = self._documentar_familia()

        # A severidade do protótipo muda: isso sim altera o procedimento.
        reconcile([self._servico("AudioSrv", "1", "4"), self._servico("BFE", "2", "4")], self.repo)

        doc = self.repo.get(chave)
        self.assertEqual(doc.doc_status, REVIEW_NEEDED)
        self.assertEqual(doc.operational["meaning"], "Partição raiz acima do limite", "documentação preservada")

    def test_ficha_de_familia_guarda_uma_amostra_tecnica(self):
        reconcile([self._servico("AudioSrv", "1"), self._servico("BFE", "2")], self.repo)
        doc = next(self.repo.all())
        self.assertTrue(doc.zabbix["representative_of_family"])
        self.assertEqual(doc.zabbix["family_instance_count"], 2)
        self.assertTrue(doc.zabbix["family_source_hash"].startswith("sha256:"))
        self.assertNotEqual(doc.zabbix["family_source_hash"], doc.zabbix["source_hash"])


class TestFichaManual(unittest.TestCase):
    def test_ficha_manual_sobrevive_a_reconciliacao(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = AlertRepository(tmp)
            repo.save(AlertDoc.manual("pagamento-nao-processado"))
            resultado = reconcile([_alerta("srv-01|disk-space-low", "100")], repo)
            self.assertEqual(resultado.summary()["disappeared"], 0, "ficha manual não some do Zabbix")
            manual = repo.get("pagamento-nao-processado")
            self.assertIsNotNone(manual)
            self.assertEqual(manual.scope, "manual")
            self.assertIsNone(manual.zabbix)


if __name__ == "__main__":
    unittest.main()
