"""Base de conhecimento já validada pelo NOC (o wiki), lida como fonte.

O wiki do NOC é conhecimento **humano e aprovado** — o oposto de uma sugestão
de máquina. Ele entra aqui como uma fonte a ser *ligada* ao que a coleta
observou, nunca como um segundo modelo de dados:

    catálogo (markdown)  ->  entrada  ->  SUGESTÃO de vínculo  ->  pessoa confirma
                                                                        |
                                                          ficha em docs/alerts/

Três regras que valem para o módulo inteiro:

* **Nada é aplicado sozinho.** O casamento entre o texto do wiki e um alerta do
  Zabbix é uma inferência, e inferência não vira fato sem confirmação. O caso
  `STALL`, que casava por substring com `Number of in*stall*ed packages`, é o
  motivo de o casamento ser por palavra inteira e de a confirmação ser humana.
* **Nada é inventado.** Cada campo da ficha importada aponta para a célula do
  wiki de onde veio. O que o wiki não diz, a ficha não afirma.
* **Nada é destrutivo.** A importação entra como rascunho (`pending_review`) e,
  por padrão, só preenche campos vazios.
"""
