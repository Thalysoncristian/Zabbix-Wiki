"""Progresso no terminal — inclusive o caminho interativo.

Os testes de CLI rodam com `stdout` redirecionado, ou seja `isatty()` falso:
eles nunca passam pela linha de andamento reescrita no lugar. Como esse é
justamente o caminho que o operador vê, ele precisa de teste próprio.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from typing import Any

from src.progress import ConsoleProgress, format_duration


def _pagina(label: str, colecionados: int, total: int, restantes: int = 0) -> dict[str, Any]:
    return {
        "event": "page", "label": label, "method": "trigger.get", "page": 1,
        "page_size": 250, "rows": 250, "collected": colecionados,
        "total": total, "remaining_pages": restantes,
    }


class TestCompacto(unittest.TestCase):
    def setUp(self):
        self.linhas: list[str] = []
        self.p = ConsoleProgress(self.linhas.append, interactive=False)

    def test_uma_linha_por_fase_e_nao_por_pagina(self):
        for i in range(1, 77):
            self.p(_pagina("triggers", i * 250, 18903))
        self.p.finish()

        self.assertEqual(len(self.linhas), 1, "76 páginas viraram uma linha só")
        self.assertIn("triggers: 19000 objetos em 76 páginas", self.linhas[0])

    def test_troca_de_fase_fecha_a_anterior(self):
        self.p(_pagina("triggers", 100, 100))
        self.p(_pagina("itens", 50, 50))
        self.p.finish()

        self.assertEqual(len(self.linhas), 2)
        self.assertIn("triggers:", self.linhas[0])
        self.assertIn("itens:", self.linhas[1])

    def test_avisos_nunca_sao_resumidos(self):
        """Silenciar um problema para caber na tela seria o pior dos mundos."""
        self.p(_pagina("triggers", 250, 1000))
        self.p({"event": "batch_reduced", "label": "triggers", "from_size": 250,
                "to_size": 125, "error": "HTTP 500"})
        self.p({"event": "page_failed", "label": "itens", "method": "item.get",
                "ids": ["1", "2"], "error": "HTTP 500"})
        self.p.finish()

        texto = "\n".join(self.linhas)
        self.assertIn("lote 250 recusado", texto)
        self.assertIn("2 objeto(s) não coletado(s)", texto)

    def test_resumos_de_contagem_somem_mas_avisos_ficam(self):
        self.p({"event": "step", "message": "18903 triggers coletados"})
        self.p({"event": "step", "message": "Aviso: selects de LLD indisponíveis"})
        self.p({"event": "step", "message": "Conectado ao Zabbix (API 7.2.1)"})

        texto = "\n".join(self.linhas)
        self.assertNotIn("18903 triggers coletados", texto, "a linha da fase já diz isso")
        self.assertIn("Aviso:", texto)
        self.assertIn("Conectado ao Zabbix", texto)

    def test_grupos_viram_uma_linha_de_escopo(self):
        for i in range(1, 22):
            self.p({"event": "group", "index": i, "groups": 21, "name": f"Grupo {i}", "hosts": 4})
        self.p({"event": "scope", "host_groups": [], "hosts": 82})

        self.assertEqual(len(self.linhas), 1, "21 grupos não viram 21 linhas")
        self.assertIn("ambiente inteiro (21 grupos) — 82 hosts", self.linhas[0])


class TestVerbose(unittest.TestCase):
    def test_verbose_imprime_pagina_a_pagina(self):
        linhas: list[str] = []
        p = ConsoleProgress(linhas.append, verbose=True, interactive=False)
        p(_pagina("triggers", 250, 1000))
        p(_pagina("triggers", 500, 1000))

        self.assertEqual(len(linhas), 2)
        self.assertIn("página 1", linhas[0])
        self.assertIn("(25%)", linhas[0])


def renderizar(saida: str) -> list[str]:
    """Aplica os `\r` como um terminal faria, devolvendo a tela resultante.

    Sem isto o teste veria a sequência de bytes (`...\r      \r`) em vez do
    que o operador enxerga. E é justamente o que ele enxerga que importa aqui:
    uma linha sobrescrita continua no buffer, mas some da tela.
    """
    tela: list[str] = []
    for bruto in saida.split("\n"):
        linha = ""
        for pedaco in bruto.split("\r"):
            # `\r` volta ao início: o pedaço seguinte sobrescreve o começo da
            # linha, e o rabo do texto anterior sobrevive só se for mais longo.
            linha = pedaco + linha[len(pedaco):]
        tela.append(linha.rstrip())
    return tela


class TestTerminalInterativo(unittest.TestCase):
    """A linha reescrita no lugar precisa funcionar em qualquer console."""

    def _rodar(self, eventos: list[dict[str, Any]], *, finish: bool = True) -> str:
        buffer = io.StringIO()
        # `interactive=True` força o caminho da linha viva mesmo sem tty;
        # `print` real vai para o buffer junto com os writes diretos.
        with redirect_stdout(buffer):
            p = ConsoleProgress(lambda t: print(t), interactive=True)
            for evento in eventos:
                p(evento)
            if finish:
                p.finish()
        return buffer.getvalue()

    def _tela(self, eventos: list[dict[str, Any]]) -> list[str]:
        return renderizar(self._rodar(eventos))

    def test_nao_usa_codigos_ansi(self):
        """O console legado do Windows mostraria `←[K` no meio do relatório."""
        saida = self._rodar([_pagina("triggers", 250, 1000, restantes=3), _pagina("triggers", 500, 1000)])
        self.assertNotIn("\033", saida, "nada de ANSI: nem todo terminal interpreta")

    def test_nao_deixa_linha_em_branco_entre_as_fases(self):
        tela = [linha for linha in self._tela([
            _pagina("triggers", 250, 250),
            _pagina("itens", 100, 100),
        ]) if linha]
        self.assertEqual(tela, [
            "  · triggers: 250 objetos em 1 página (0s)",
            "  · itens: 100 objetos em 1 página (0s)",
        ])

    def test_linha_viva_e_apagada_e_nao_sobra_lixo(self):
        """Uma linha longa seguida de uma curta não pode deixar o rabo da longa."""
        tela = [linha for linha in self._tela([
            _pagina("uma fase com nome bem comprido para ocupar a linha inteira", 999, 1000, restantes=9),
            _pagina("x", 1, 1),
        ]) if linha]
        self.assertEqual(len(tela), 2)
        self.assertTrue(tela[1].endswith("x: 1 objeto em 1 página (0s)"), tela[1])
        for linha in tela:
            self.assertNotIn("restante(s)", linha, "o texto de andamento não pode sobreviver")

    def test_finish_limpa_a_linha_de_andamento(self):
        tela = self._tela([{"event": "phase", "name": "descoberta", "detail": "lote 3"}])
        self.assertEqual([linha for linha in tela if linha], [], "a tela fica limpa ao terminar")

    def test_linha_viva_nao_passa_da_largura_do_terminal(self):
        """Se ela quebrar em duas, o `\r` seguinte deixa metade como lixo.

        Só a linha de ANDAMENTO é truncada. A linha definitiva vai inteira: se
        ela quebrar em duas, nada é sobrescrito depois e nenhum lixo sobra.
        """
        viva = self._rodar([_pagina("f" * 500, 1, 1000, restantes=9)], finish=False)
        self.assertTrue(viva.startswith("\r"))
        self.assertLessEqual(len(viva.lstrip("\r")), 200, "linha de andamento longa demais")
        self.assertNotIn("\n", viva, "andamento não quebra linha")


class TestFormatDuration(unittest.TestCase):
    def test_segundos_minutos_horas(self):
        self.assertEqual(format_duration(5), "5s")
        self.assertEqual(format_duration(58.2), "58s")
        self.assertEqual(format_duration(125), "2m05s")
        self.assertEqual(format_duration(3725), "1h02m")

    def test_negativo_nao_quebra(self):
        self.assertEqual(format_duration(-1), "0s")


if __name__ == "__main__":
    unittest.main()
