"""Redação de segredos (item 20 da Fase 3).

O caso que motivou tudo é real: a coleta do ambiente inteiro trouxe uma chave
de acesso da AWS em texto claro dentro de uma expressão de trigger.
"""

from __future__ import annotations

import unittest

from src.redact import contains_secret, redact_snapshot_data, redact_text, redact_value

#: A expressão real que apareceu na coleta, com o segredo trocado por um
#: valor de mesmo formato. Nenhum segredo verdadeiro entra no repositório.
EXPRESSAO_REAL = (
    'avg(/Saq - AWS/aws_check.py[--access-key, "AKIAIOSFODNN7EXAMPLE", '
    '--secret-key, "wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY", --region, "sa-east-1", '
    '--service, "lambda", --metric-name, "Errors"],5m) >= 5'
)


class TestSegredosSaoRedigidos(unittest.TestCase):
    def test_chave_e_segredo_da_aws_somem_da_expressao(self):
        redigido, total = redact_text(EXPRESSAO_REAL)

        self.assertEqual(total, 2)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", redigido)
        self.assertNotIn("wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLEKEY", redigido)
        self.assertIn("[REDACTED:", redigido)

    def test_estrutura_operacional_e_preservada(self):
        """Redigir não pode destruir a utilidade do alerta."""
        redigido, _ = redact_text(EXPRESSAO_REAL)

        for pedaco in ("--access-key", "--secret-key", "--region", '"sa-east-1"',
                       "--metric-name", '"Errors"', "avg(", "5m) >= 5"):
            self.assertIn(pedaco, redigido, f"{pedaco} deveria ter sido preservado")

    def test_id_de_chave_aws_solto_tambem_e_pego(self):
        redigido, total = redact_text("comentário: usar AKIAIOSFODNN7EXAMPLE no script")
        self.assertEqual(total, 1)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", redigido)

    def test_token_bearer(self):
        redigido, total = redact_text("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        self.assertEqual(total, 1)
        self.assertIn("Bearer [REDACTED:", redigido)
        self.assertNotIn("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9", redigido)

    def test_password_sem_aspas(self):
        redigido, total = redact_text("mysql.get[--user=zbx,--password=SenhaSuperSecreta123]")
        self.assertEqual(total, 1)
        self.assertNotIn("SenhaSuperSecreta123", redigido)
        self.assertIn("--user=zbx", redigido, "o usuário não é segredo e fica")


class TestFalsosPositivos(unittest.TestCase):
    """Redigir demais destrói informação operacional sem esconder segredo."""

    def test_macro_do_zabbix_nao_e_segredo(self):
        for texto in ("password={$SENHA}", "token: {$API.TOKEN}", '"{$VPN.STATE.CONTROL}"=1'):
            redigido, total = redact_text(texto)
            self.assertEqual(total, 0, texto)
            self.assertEqual(redigido, texto)

    def test_palavra_sem_valor_fica(self):
        for texto in (
            "Certificate password expires in 30 days",
            "A senha do banco mudou, avisar o time",
            "Token de sessão inválido — reautenticar",
        ):
            redigido, total = redact_text(texto)
            self.assertEqual(total, 0, texto)
            self.assertEqual(redigido, texto)

    def test_expressao_normal_passa_intacta(self):
        expressao = 'min(/host/vfs.fs.size[/,pfree],5m)<{$VFS.FS.PFREE.MIN.CRIT:"/"}'
        redigido, total = redact_text(expressao)
        self.assertEqual((redigido, total), (expressao, 0))


class TestEstabilidade(unittest.TestCase):
    def test_o_mesmo_segredo_da_sempre_o_mesmo_marcador(self):
        """Senão o source_hash mudaria a cada coleta e tudo cairia em revisão."""
        um, _ = redact_text(EXPRESSAO_REAL)
        outro, _ = redact_text(EXPRESSAO_REAL)
        self.assertEqual(um, outro)

    def test_segredos_diferentes_dao_marcadores_diferentes(self):
        """Senão dois triggers distintos passariam a colidir em silêncio."""
        a, _ = redact_text('token="AAAAAAAAAAAAAAAA"')
        b, _ = redact_text('token="BBBBBBBBBBBBBBBB"')
        self.assertNotEqual(a, b)

    def test_redigir_duas_vezes_nao_muda_nada(self):
        uma, _ = redact_text(EXPRESSAO_REAL)
        duas, total = redact_text(uma)
        self.assertEqual(uma, duas)
        self.assertEqual(total, 0, "um marcador já redigido não é redigido de novo")


class TestEstruturas(unittest.TestCase):
    def test_redige_dentro_de_dicts_e_listas(self):
        linha = {
            "triggerid": "1",
            "expression": EXPRESSAO_REAL,
            "items": [{"itemid": "9", "key_": 'aws[--secret-key, "AKIAIOSFODNN7EXAMPLE"]'}],
        }
        redigido, total = redact_value(linha)

        self.assertEqual(total, 3, "2 na expressão + 1 na chave do item")
        self.assertEqual(redigido["triggerid"], "1", "IDs não são tocados")
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", str(redigido))

    def test_campos_que_nao_sao_texto_nao_sao_varridos(self):
        """Varrer tudo faria a redação passar por IDs e enums sem ganho."""
        linha = {"hostid": "secret=abcdefghijkl", "expression": "secret=abcdefghijkl"}
        redigido, total = redact_value(linha)
        self.assertEqual(redigido["hostid"], "secret=abcdefghijkl")
        self.assertNotIn("abcdefghijkl", redigido["expression"])
        self.assertEqual(total, 1)

    def test_relatorio_de_redacao_e_auditavel(self):
        dados = {"triggers": [{"triggerid": "1", "expression": EXPRESSAO_REAL}], "hosts": [{"hostid": "2"}]}
        _, relatorio = redact_snapshot_data(dados)

        self.assertTrue(relatorio["enabled"])
        self.assertEqual(relatorio["values_redacted"], 2)
        self.assertEqual(relatorio["by_collection"], {"triggers": 2})
        self.assertIn("REDACTED", relatorio["note"])


class TestDeteccao(unittest.TestCase):
    def test_contains_secret(self):
        self.assertTrue(contains_secret(EXPRESSAO_REAL))
        self.assertFalse(contains_secret("min(/host/icmpping,5m)=0"))


if __name__ == "__main__":
    unittest.main()
