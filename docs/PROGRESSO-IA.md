# Progresso das sessões de IA

Registro do que cada sessão de documentação assistida por IA produziu. Serve
para saber onde a próxima começa e para auditar o que foi escrito por máquina —
o conteúdo aqui é **rascunho técnico**, e continua precisando de validação
humana antes de virar procedimento oficial.

Instruções da sessão: [PROMPT-AGENTE-IA.md](PROMPT-AGENTE-IA.md)

---

## Formato

Uma linha por sessão, mais recente no topo:

```
### AAAA-MM-DD — <quem/qual modelo>
- **Escreveu:** N fichas em rascunho (liste os clientes ou categorias)
- **Marcou não aplicável:** N fichas, e o motivo
- **Deixou em aberto:** o que só o time do NOC pode decidir
- **Status depois:** cole a saída de `python main.py status`
```

---

## Sessões

### 2026-09-06 — Claude (aprovação em lote dos rascunhos)

O time decidiu aprovar tudo e corrigir o que aparecer de errado no uso. Como os
campos organizacionais estavam vazios e a máquina de estados recusa
`documented` sem eles, "aprovar" exigiu preenchê-los — e o único jeito
defensável de fazer isso sem inventar foi **extrapolar o padrão que as fichas
vindas dos manuais do time já estabeleceram**.

- **Aprovou:** 68 fichas, de `pending_review` para `documented`.
- **Roteamento atribuído** (todos extrapolados, nenhum informado especificamente
  para aquele alerta):

  | Cliente | Time | Fila | Fichas |
  |---|---|---|---:|
  | Vibe Tecnologia | Infraestrutura | DeskManager (Teams / Rafael Sales) | 44 |
  | Chubb | NOC | DeskManager | 13 |
  | Vibe Tecnologia | NOC / Infra | DeskManager | 5 |
  | Vibe Tecnologia | NOC | DeskManager | 2 |
  | Vibe Tecnologia | SOC | DeskManager → fila SOC | 2 |
  | Chubb | NOC (N1) → Suporte BMC | DeskManager | 1 |
  | Chubb | Suporte DEV | DeskManager | 1 |

- **Não aprovou 11**, por falta de qualquer base: as 4 do **SAQ** (nenhuma ficha
  validada desse cliente existe, então não há padrão de onde extrapolar) e 7 de
  clientes que outro NOC atende.
- **Como auditar:** toda ficha assim leva `ROTEAMENTO EXTRAPOLADO` nas notas.
  ```bash
  grep -l "ROTEAMENTO EXTRAPOLADO" docs/alerts/*.json | wc -l    # 68
  ```
  O `resolution_criteria` também é genérico e traz `[EXTRAPOLADO]` no texto.
- **Status depois:** 450 sem procedimento · 11 rascunhos · **119 validadas** ·
  24 não aplicáveis. Wiki passou de 41 para **106 procedimentos**.

### 2026-09-06 — Claude (validação do prompt)

Sessão curta, para provar que as instruções deste diretório funcionam de ponta
a ponta antes de outra IA depender delas.

- **Escreveu:** 1 ficha — `{#CODCHAMADO}: {#ASSUNTO} - Aguardando cliente
  (5 dias úteis)`, 277 alertas do DeskManager. Serve como exemplo do padrão
  esperado: números reais no `meaning`, o risco das 833 dependências entre os
  estágios do mesmo chamado, e `[A DEFINIR]` no que depende do time.
- **Verificou a trava:** tentar gravar `documented` sem `requires_ticket` e
  `resolution_criteria` é recusado com `HTTP 422` e mensagem explícita. Uma IA
  que tentar forçar vai bater nessa parede, como deve.
- **Deixou em aberto:** quem cobra o retorno do cliente nesses chamados, e se o
  alerta gera ação ou é indicador de SLA para relatório.
- **Status depois:** 450 sem procedimento · 79 rascunhos · 51 validadas ·
  24 não aplicáveis.

### 2026-09-06 — Claude (sessão inicial, com o time)

- **Escreveu:** 79 rascunhos técnicos cobrindo 100% das regras operacionais
  (todas as 85, sendo 14 duplicatas de outra), e 51 fichas validadas a partir
  do catálogo do NOC, do manual da Chubb, do manual da Votorantim e da wiki de
  rede — essas com time, fila e SLA reais, porque vieram do time.
- **Marcou não aplicável:** 24 fichas de alerta de teste. Sete regras ficaram
  intocadas por terem alerta legítimo junto.
- **Deixou em aberto:** rotação das credenciais AWS/PIX expostas no Zabbix; os
  campos "A confirmar" da matriz de acionamento; o IP divergente do RDP; a
  tolerância de perda de pacotes em link; o dono de 4 hosts sem prefixo.
- **Status depois:**
  ```
  Fichas       : 604
  Cobertura    : 51/580 (8.8%) documentadas ou revisadas
                 (24 não aplicáveis fora da conta — alerta de teste e afins)
    undocumented     451
    pending_review    78
    documented        51
    not_applicable    24
  ```

---

## Fila de trabalho

**413 fichas sem procedimento** nos clientes que o Master Support atende:

| Cliente | Fichas | Alertas |
|---|---:|---:|
| Vibe Tecnologia | 343 | 2.050 |
| Chubb | 41 | 195 |
| SAQ (pagamentos) | 22 | 103 |
| Master Support (interno) | 4 | 29 |
| Strada | 2 | 3 |
| Votorantim | 1 | 8.131 — **não documentar**, é a malha do cliente |

As de Carguero, Hocta, Pagol e Banpará (38 fichas) ficam de fora: outro NOC
atende e elas não entram na wiki.
