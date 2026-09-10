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


class TestSegredoSemAspas(unittest.TestCase):
    """Casos reais achados em triggers de PIX do ambiente coletado.

    Os dois passavam batido: a redação cobria `--clientsecret, "valor"` (com
    aspas) e deixava `--clientsecret,valor` — o mesmo segredo, escrito do jeito
    que a chave de item do Zabbix realmente usa.
    """

    #: Formato real do trigger, com vírgula separando parâmetro e valor.
    PIX = ('pix.check[--url,{$PIX_API_URL},--clientid,monitor@exemplo.com,'
           '--clientsecret,21232F297A57A5A743894A0E4A801FC3,'
           '--hmacsecret,77331094e9ab7c1de9e306b210f4c8a1]')

    def test_clientsecret_separado_por_virgula(self):
        redigido, _ = redact_text(self.PIX)
        self.assertNotIn("21232F297A57A5A743894A0E4A801FC3", redigido)

    def test_hmacsecret_tambem_e_segredo(self):
        """`secret` puro nunca casava dentro de `hmacsecret`: o lookbehind
        exige começo de palavra, e antes de `secret` vinha `hmac`."""
        redigido, _ = redact_text(self.PIX)
        self.assertNotIn("77331094e9ab7c1de9e306b210f4c8a1", redigido)

    def test_o_que_nao_e_segredo_continua_legivel(self):
        """Redigir não pode destruir a utilidade do alerta.

        O `--clientid` saiu desta lista: ele era tratado como "usuário, não
        segredo" e ficava em claro ao lado do `--clientsecret` redigido. No
        ambiente real isso deixava a conta de serviço exposta em 13 fichas —
        metade do par de credenciais, entregue de graça. Ver
        `TestMetadeIdentificadora`.
        """
        redigido, total = redact_text(self.PIX)
        self.assertEqual(total, 3)
        self.assertIn("pix.check", redigido)
        self.assertIn("{$PIX_API_URL}", redigido, "macro é referência, não valor")
        self.assertIn("--url,{$PIX_API_URL}", redigido, "parâmetro comum continua legível")

    def test_virgula_nao_cria_falso_positivo(self):
        """A vírgula agora separa nome de valor — não pode redigir parâmetro
        legítimo de chave de item."""
        for texto in ("last(/host/trap[token,5m])>0", "min(/host/icmpping,5m)=0"):
            _, total = redact_text(texto)
            self.assertEqual(total, 0, texto)


class TestAlertaNormalizado(unittest.TestCase):
    """A redação também precisa alcançar o alerta JÁ normalizado.

    No fluxo normal ela roda antes da normalização, então bastariam os nomes
    do snapshot bruto. Mas um snapshot coletado por uma versão anterior à
    redação só pode ser limpo depois — e aí os campos já se chamam
    `expression_expanded`, `expression_signature` e afins. Sem eles na
    allowlist, a função não encontrava nada e devolvia "0 valores redigidos"
    sobre um arquivo que tinha a credencial em texto claro.
    """

    def _alerta(self):
        return {
            "alert_key": "saq-aws|lambda-erro",
            "alert_key_basis_description": "Lambda com erro",
            "zabbix": {
                "triggerid": "77",
                "description_raw": "Lambda está a registrar erros",
                "expression_raw": "{71870} >= 5",
                "expression_expanded": EXPRESSAO_REAL,
                "expression_signature": EXPRESSAO_REAL.replace("/Saq - AWS/", "/{HOST}/"),
                "recovery_expression_expanded": "",
            },
        }

    def test_redige_os_campos_derivados_da_normalizacao(self):
        redigido, total = redact_value(self._alerta())
        zbx = redigido["zabbix"]
        self.assertGreater(total, 0, "a credencial precisa ser encontrada no alerta normalizado")
        for campo in ("expression_expanded", "expression_signature"):
            self.assertNotIn("AKIAIOSFODNN7EXAMPLE", zbx[campo], f"{campo} continuou com a chave")
            self.assertIn("[REDACTED:", zbx[campo])

    def test_nao_toca_no_que_nao_e_segredo(self):
        redigido, _ = redact_value(self._alerta())
        self.assertEqual(redigido["zabbix"]["triggerid"], "77")
        self.assertEqual(redigido["zabbix"]["description_raw"], "Lambda está a registrar erros")

    def test_redigir_duas_vezes_nao_muda_nada(self):
        """Idempotência: sem isso, uma segunda passada mudaria o hash e jogaria
        a documentação inteira em `review_needed` sem motivo."""
        uma_vez, _ = redact_value(self._alerta())
        duas_vezes, total = redact_value(uma_vez)
        self.assertEqual(duas_vezes, uma_vez)
        self.assertEqual(total, 0)


class TestMetadeIdentificadora(unittest.TestCase):
    """A conta de serviço é credencial tanto quanto o segredo dela.

    Achado no ambiente real: `--clientsecret` era redigido e o
    `--clientid,monitoracaojd@saq.com` ao lado ficava em texto claro, em 13
    ocorrências. Quem lia a ficha já saía com metade do par.
    """

    def test_clientid_e_redigido(self):
        redigido, total = redact_text(
            "check_pix_api.py[--clientid,servico@empresa.com,--clientsecret,s3gr3d0abcdef]"
        )
        self.assertNotIn("servico@empresa.com", redigido)
        self.assertNotIn("s3gr3d0abcdef", redigido)
        self.assertEqual(total, 2)

    def test_username_e_login_tambem(self):
        for chave in ("--username=svc_app_prod", "login=svc_app_prod"):
            self.assertNotIn("svc_app_prod", redact_text(chave)[0])

    def test_user_sozinho_NAO_e_redigido(self):
        """`--user` aparece em item legítimo. Redigi-lo destruiria dado
        operacional para proteger o que não é segredo."""
        texto = "proc.num[,postgres,--user,zabbix]"
        self.assertEqual(redact_text(texto), (texto, 0))

    def test_segmento_de_url_nao_e_nome_de_argumento(self):
        """`https://…/login,Verificar` casava com `login` e a redação engolia
        "Verificar" — o nome do passo do cenário web, dado operacional puro."""
        texto = 'web.test.rspcode[https://app2.exemplo.com.br/login,Verificar]'
        self.assertEqual(redact_text(texto), (texto, 0))


class TestIdempotenciaDentroDeChaveDeItem(unittest.TestCase):
    """O marcador precisa sobreviver a uma segunda passada mesmo sem o `]`.

    Numa chave de item, `]` fica fora da classe de caracteres do valor, então o
    grupo capturado é `[REDACTED:4bdf095e` — truncado. Com a guarda ancorada em
    `$`, ela não disparava: a segunda passada redigia o próprio marcador,
    gerando um hash novo e um `]` órfão no texto.
    """

    CHAVE = ("min(/{HOST}/check_pix_api.py[--mode,check,--clientid,conta@empresa.com,"
             "--clientsecret,[REDACTED:4bdf095e],--hmacsecret,[REDACTED:4514f38a]])")

    def test_marcador_existente_sobrevive(self):
        redigido, _ = redact_text(self.CHAVE)
        self.assertIn("[REDACTED:4bdf095e]", redigido)
        self.assertIn("[REDACTED:4514f38a]", redigido)
        self.assertNotIn("]]]", redigido, "colchete órfão: o marcador foi re-redigido")

    def test_passadas_seguintes_nao_mudam_nada(self):
        uma, _ = redact_text(self.CHAVE)
        duas, total = redact_text(uma)
        self.assertEqual(duas, uma)
        self.assertEqual(total, 0)


class TestDeteccao(unittest.TestCase):
    def test_contains_secret(self):
        self.assertTrue(contains_secret(EXPRESSAO_REAL))
        self.assertFalse(contains_secret("min(/host/icmpping,5m)=0"))


if __name__ == "__main__":
    unittest.main()
