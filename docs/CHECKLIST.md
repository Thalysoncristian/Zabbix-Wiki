# Checklist do Zabbix-Wiki

Estado do projeto e o que falta. Atualizado a cada entrega — item concluído é
marcado aqui, com a data e o commit.

**Atualizado em:** 2026-09-06
**Situação:** 119 validadas · 11 rascunhos · 450 sem procedimento · 24 não aplicáveis · wiki com 103 procedimentos

---

## 🔴 Bloqueadores — segurança

- [ ] **Rotacionar as credenciais expostas no Zabbix**
  Chave AWS (`Saq - AWS`, 57 triggers) e clientsecret/hmacsecret do PIX
  (`Saq - Pix`, 5 triggers) estão em texto claro dentro da expressão de trigger.
  Quem tem leitura na API enxerga. Redigir o arquivo local **não desfaz** isso.
  → Detalhes em [SEGURANCA-credenciais-expostas.md](SEGURANCA-credenciais-expostas.md)
  → *Pronto quando:* credenciais rotacionadas na AWS/PIX **e** substituídas por
  macro secreta no Zabbix. Conferir com o `grep` do próprio documento.

- [ ] **Revisar quem tem permissão de leitura na API do Zabbix**
  Enquanto as credenciais estiveram em claro, qualquer conta com leitura pôde
  vê-las. Vale saber quem são.

---

## 🟠 Decisões de vocês — travam trabalho meu

- [ ] **IP do RDP do Banpará:** o catálogo do NOC diz `10.0.10.25`, o Zabbix
  real tem `10.0.20.25`. Qual está certo?
  *(Obs.: o Banpará hoje está fora da wiki — outro NOC atende.)*

- [ ] **Campos "A confirmar" na matriz de acionamento**
  Horário de atendimento do Suporte Oracle, Suporte BMC, Suporte DEV, RH,
  Administrativo e Carlos Favacho; escalonamento da Infraestrutura.
  → [escalation_matrix.md](escalation_matrix.md)

- [ ] **Telefone do Marcos Paulo Pinheiro Correa**
  Consta como contato de acionamento crítico da Chubb, sem número. Se o Bruno
  não atender, não há segundo contato utilizável.

- [ ] **Contradição no manual da Chubb: quem reexecuta job do Control-M?**
  O texto geral diz que o N1 pode ("quando permitido"); a seção específica e a
  matriz atribuem a reexecução (até 3x) ao N2 (Bruno Mendes).

- [ ] **Deadline das 08:00 do Control-M (Chubb)**
  Aparece como prioridade de normalização, mas sem regra de escalonamento
  amarrada. O que acontece se passar das 8h?

- [ ] **Confirmar o dono de 4 hosts sem prefixo de cliente**
  Caíram na Vibe pelo host group, não pelo nome — ainda é palpite meu:
  `SRVCYBERARQ`, `SRV_INCONTROL_2026`, `Windows bob`, `test temp`.
  → Ajuste em [clients.json](../clients.json) e rode `python main.py wiki`.
  *(Os 4 roteadores foram confirmados — ver Concluído.)*

- [ ] **7 fichas de regra com alerta de teste no meio**
  Não dava para marcar como não aplicável: cobrem alertas legítimos junto.
  | Ficha | Teste / total |
  |---|---|
  | `rule\|applications--api_web` (Pagol) | 32 de 34 |
  | `rule\|applications--cpu` | 5 de 7 |
  | `rule\|applications--job` (Control-M) | 8.127 de 16.479 |
  | `rule\|cliente-carguero--api_web` | 15 de 44 |
  | `rule\|applications--service` | 1 de 4 |
  | `rule\|vibe-tecnologia--api_web` | 1 de 13 |
  | `rule\|zabbix-servers--system_state` | 1 de 15 |
  → *Decisão de vocês:* separar os triggers de teste no Zabbix resolveria na
  origem. Enquanto isso, as regras seguem documentáveis normalmente.

- [ ] **Definir a tolerância de perda de pacotes em link**
  A ficha de `ICMP: High ICMP ping loss` nos roteadores ficou como rascunho por
  causa disso: a wiki de rede não diz por quanto tempo tolerar antes de acionar
  a operadora, e acionar a cada oscilação queima o canal.

---

## 🟡 Documentação — o grosso do trabalho

- [ ] **Conferir o roteamento das 68 fichas aprovadas por extrapolação**
  O time optou por aprovar em lote e corrigir no uso. O time e a fila dessas
  fichas foram **deduzidos do padrão** das fichas que vieram dos manuais — não
  foram informados para cada alerta. Cada uma leva `ROTEAMENTO EXTRAPOLADO` nas
  notas, e o `resolution_criteria` é genérico.
  ```bash
  grep -l "ROTEAMENTO EXTRAPOLADO" docs/alerts/*.json
  ```
  → *Maior risco:* as 44 da Vibe que foram para **Infraestrutura · DeskManager ·
  Rafael Sales**. Se alguma categoria (licenças, banco de dados, certificados)
  tiver outro dono, são várias fichas apontando para o time errado.

- [ ] **Definir o roteamento do SAQ — 4 fichas continuam em rascunho**
  Não existe nenhuma ficha validada do SAQ, então não havia padrão de onde
  extrapolar: Lambda/AWS, PIX, certificados e conectividade. Quem atende?

- [ ] **450 fichas sem procedimento nenhum** (413 em clientes nossos)
  São famílias técnicas que nenhuma regra cobre ou que ninguém tocou.
  → **Documentação assistida por IA:** o briefing está em
  [PROMPT-AGENTE-IA.md](PROMPT-AGENTE-IA.md) e o registro das sessões em
  [PROGRESSO-IA.md](PROGRESSO-IA.md). A IA escreve o rascunho técnico; time,
  fila e SLA continuam sendo do humano.
  → `python main.py status` mostra a contagem.

- [ ] **SAQ e Strada ainda não aparecem na wiki**
  Nenhuma ficha validada desses clientes — só rascunhos. SAQ tem 93 alertas em
  10 hosts (PIX, certificados, AWS); Strada tem 3.

- [ ] **Votorantim: Flood de alertas de e-mail (regra dos 15 min)**
  Está no manual, mas não achei trigger correspondente no snapshot. Confirmar se
  chega como alerta em algum lugar.

- [ ] **Votorantim: Long Run e Late Submission**
  O Zabbix só vê `Ended Not Ok`. Long Run parece ser status de runtime dentro do
  próprio Control-M — confirmar se gera alerta pra vocês.

---

## 🔵 Código e melhorias

- [ ] **Corrigir 4 classificações erradas da taxonomia**
  Todas por substring sem fronteira de palavra:
  | Alerta | Caiu em | Motivo |
  |---|---|---|
  | `Uso de Disco acima de 90% - ords-dev-vibe` | Nuvem/AWS | "o**rds**-dev" contém `rds` |
  | `Uso de Disco acima de 90% - grafana` | Hardware | "gra**fan**a" contém `fan` |
  | `API - Vibe (processamento) indisponível` | CPU | menciona "processamento" |
  | `Licença AV/IPS/FortiCloud expira` | Certificados | menciona "expira" (são licenças) |
  → Mexer nos limites de palavra reclassifica alertas em massa: merece mudança
  própria, com teste.

- [ ] **Criar categoria de impressora na taxonomia**
  Os 4 alertas de toner (`hp.*.toner.now`) caem em "Outros" e aparecem assim na
  wiki, numa aba genérica sem sentido operacional.

- [ ] **Editar ficha `manual` pela interface**
  As 12 fichas de RH Cloud/MSMonitor aparecem na tela, mas só podem ser editadas
  por arquivo — a rota de escrita espera uma família do snapshot.

- [ ] **`alert_key` dos jobs Control-M muda todo dia**
  O `ODate` entra na chave (`...odate-260904...` vs `...odate-260905...`), então
  documentação presa a um alert_key de job específico fica órfã em 24h. Por isso
  o caso do `TransfereArquivoChubb` foi documentado na regra, não como override.
  → Corrigir exigiria tratar `{#JOB.ORDERDATE}` como ruído na chave.

- [ ] **Definir a tolerância de "pico curto" antes de abrir chamado**
  Várias fichas de CPU, memória e I/O dizem para não abrir chamado por pico
  pontual, mas nenhuma diz quanto tempo é "pontual". Ficou registrado em
  `EM ABERTO` nas observações dessas fichas.

---

## ⚪ Manutenção contínua

- [ ] **Definir cadência de `collect` + `reconcile`**
  Diária? Semanal? Sem isso o snapshot envelhece e o `review_needed` nunca
  dispara.

- [ ] **Definir quem revisa `review_needed`**
  Quando o Zabbix muda um trigger documentado, a ficha cai nesse estado. Falta
  dono.

- [ ] **Publicar a wiki no Wiki.js** — *prematuro por enquanto*
  `python main.py wiki` gera [wiki-noc.md](wiki-noc.md) pronto pra colar, mas
  com 41 procedimentos de um universo de ~110 nos rascunhos (e 450 sem nada), a
  página ainda cobre pouco do que o plantão encontra. Vale publicar quando os
  rascunhos estiverem validados. O gerador não envelhece esperando: é um
  comando, roda quando quiser.

---

## ✅ Concluído

- [x] **Coleta read-only do Zabbix** — 18.903 triggers, 78 hosts, sem escrita `370dac5`
- [x] **Modelo de ficha com 3 camadas** (`zabbix` / `ai_suggestion` / `operational`) `370dac5`
- [x] **Interface web local** + escopo operacional `53b9a03` `5f20b99`
- [x] **Camada de regras operacionais** — 521 famílias → 85 regras `370dac5`
- [x] **Bug do console Windows (cp1252)** — `main.py scope` morria com
  `UnicodeEncodeError` antes de mostrar qualquer dado — 2026-09-06 `8869d5f`
- [x] **Detecção de regras sobrepostas** — 27 de 85 regras cobriam os mesmos
  alertas de outra; o mesmo procedimento foi escrito duas vezes para o Control-M
  antes disso existir — 2026-09-06 `d489eaa`
- [x] **Alertas manuais visíveis na interface** — as 12 fichas de RH Cloud e
  MSMonitor existiam em disco e só apareciam pra quem lia JSON — 2026-09-06 `c348cd7`
- [x] **Dois furos na redação de segredos** — vírgula como separador sem aspas e
  `hmacsecret`; ambos deixavam credencial real passar — 2026-09-06 `d84bb96`
- [x] **Importar o catálogo do NOC e o manual da Chubb** — 40 fichas com time,
  fila e SLA reais — 2026-09-06 `78d4ec5`
- [x] **Cobrir 100% das regras** — 50 clusters restantes documentados; 1.931 de
  1.931 alertas em regra têm ficha — 2026-09-06 `78d4ec5`
- [x] **Gerador da wiki (ETAPA 10)** — `python main.py wiki`, dialeto Wiki.js,
  determinístico, só o que foi validado — 2026-09-06 `88b1b44`
- [x] **Wiki organizada por cliente** — cada cliente com sua matriz de
  acionamento; cliente de outro NOC fica de fora — 2026-09-06 `9a8ee80`
- [x] **Manual da Votorantim** — agente Control-M fora, com as 4 fases, a matriz
  de tolerância e o escalonamento N2→N3 — 2026-09-06 `a868f36`
- [x] **Escopo por regra de descoberta** — excluir o host inteiro escondia os 60
  alertas de agente que o NOC atende — 2026-09-06 `47ddbed`
- [x] **Wiki de rede: acionamento de operadora** — 6 fichas de link e
  alcançabilidade (Embratel principal, Vellon/Interconnect backup, Oi), com
  canal e sequência de atendimento de cada operadora — 2026-09-06
- [x] **Dono dos 4 roteadores confirmado: Vibe Tecnologia** — a wiki de rede
  mostra que o CNPJ usado nos contratos (`13956365`, E. SANTOS E L. SILVA LTDA)
  é o mesmo da Vibe. `Embratel - Roteador [Cisco]`, `Interconect - Roteador`,
  `Oi - Roteador [Huawei]` e `RT_CISCO_EBT` são links da fábrica — 2026-09-06
- [x] **Triagem dos alertas "TESTE"** — dos 8.200, só 69 aparecem no escopo do
  NOC e apenas **5 são trigger de teste de verdade**. Os outros 6 do nosso lado
  são falso positivo do nome: 5 jobs reais da Chubb cuja *SubApplication* se
  chama TESTE, e um incidente real do ONESecure com "Teste" no título do ticket.
  **Por isso não existe filtro automático por "TESTE"**: ele esconderia jobs de
  produção e um incidente de segurança — exatamente a falha silenciosa que o
  escopo evita — 2026-09-06
- [x] **Tirar os alertas de teste da base** — 24 fichas marcadas como
  `not_applicable`, com o motivo registrado. Não foram apagadas de propósito: o
  `reconcile` da próxima coleta recriaria cada uma como `undocumented` e a
  poluição voltaria. Uma ficha de regra só foi marcada quando **todos** os
  alertas cobertos eram de teste — 7 ficaram intocadas por terem alerta
  legítimo junto — 2026-09-06 `dbfaee1`
- [x] **Cobertura não conta mais o que não se aplica** — `python main.py status`
  tirou as `not_applicable` do denominador. Antes, alerta de teste contava como
  dívida e a cobertura nunca chegaria a 100% por mais que o time documentasse
  tudo que importa — 2026-09-06 `dbfaee1`

---

## Como conferir o estado

```bash
python main.py status    # cobertura das fichas
python main.py scope     # o que o NOC vê, e o que fica de fora
python main.py wiki      # regenera a página, dizendo o que ficou de fora
python -m unittest discover -s tests -t .
```
