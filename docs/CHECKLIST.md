# Checklist do Zabbix-Wiki

Estado do projeto e o que falta. Atualizado a cada entrega — item concluído é
marcado aqui, com a data e o commit.

**Atualizado em:** 2026-09-06
**Situação:** 46 fichas validadas · 79 rascunhos · 479 sem procedimento · wiki gerando 4 clientes

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

- [ ] **Confirmar o dono de 8 hosts sem prefixo de cliente**
  Caíram na Vibe pelo host group, não pelo nome — é palpite meu:
  `Embratel - Roteador [Cisco]`, `Oi - Roteador [Huawei]`,
  `Interconect - Roteador`, `RT_CISCO_EBT`, `SRVCYBERARQ`,
  `SRV_INCONTROL_2026`, `Windows bob`, `test temp`.
  → Ajuste em [clients.json](../clients.json) e rode `python main.py wiki`.

- [ ] **Alertas de TESTE em produção — 8.200 no total**
  | Host | Alertas | Observação |
  |---|---|---|
  | Control-M PRD Votorantim | 8.131 | prefixo `[TESTE - DENISON]`, é metade do ambiente |
  | Pagol - Grafana | 41 | outro NOC atende |
  | Carguero (API + Grafana) | 17 | outro NOC atende |
  | **Control-M server [IN01]** | **5** | **é da Chubb, nosso** |
  | Vibe - Grafana / Ferramentas / Zabbix server | 4 | nossos |
  | Desk Manager | 1 | **Disaster**, infra nossa |
  | ONESecure | 1 | infra nossa |
  → *Pronto quando:* o time confirmar quais podem ser desligados no Zabbix.

- [ ] **`applications--api_web` (Pagol/Bankeiro) é produção?**
  Os 30 alertas têm prefixo `TESTE`. Cliente atendido por outro NOC — pode ser
  que nem precise de procedimento nosso.

---

## 🟡 Documentação — o grosso do trabalho

- [ ] **Validar os 79 rascunhos técnicos** (`pending_review` → `documented`)
  Cada um já tem contexto, sintomas, verificações e ressalvas escritas. Falta o
  que só vocês sabem: time, fila, SLA e critério de resolução.
  → `python main.py serve` → Regras → filtrar "Rascunho"
  → *Impacto:* leva a wiki de 37 para ~110 procedimentos.

- [ ] **479 fichas sem procedimento nenhum**
  São famílias técnicas que nenhuma regra cobre ou que ninguém tocou. A maioria
  é cauda longa de baixo volume.
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

- [ ] **Deduplicar regras sobrepostas**
  Hoje o sistema **avisa** (`⚠ sobreposta`) quando duas regras cobrem os mesmos
  alertas — 27 de 85 regras, 24 grupos. Documentar uma vale pelas outras, mas o
  operador precisa saber disso lendo o aviso.

---

## ⚪ Manutenção contínua

- [ ] **Definir cadência de `collect` + `reconcile`**
  Diária? Semanal? Sem isso o snapshot envelhece e o `review_needed` nunca
  dispara.

- [ ] **Definir quem revisa `review_needed`**
  Quando o Zabbix muda um trigger documentado, a ficha cai nesse estado. Falta
  dono.

- [ ] **Publicar a wiki no Wiki.js**
  `python main.py wiki` gera [wiki-noc.md](wiki-noc.md) pronto pra colar. Falta
  definir onde publica e com que frequência regenera.

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

---

## Como conferir o estado

```bash
python main.py status    # cobertura das fichas
python main.py scope     # o que o NOC vê, e o que fica de fora
python main.py wiki      # regenera a página, dizendo o que ficou de fora
python -m unittest discover -s tests -t .
```
