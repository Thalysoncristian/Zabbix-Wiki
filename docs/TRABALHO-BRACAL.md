# Trabalho braçal — o que precisa ser preenchido à mão

Este documento é a fila de execução. O [CHECKLIST.md](CHECKLIST.md) diz *o que*
falta no projeto; aqui está *como fazer* a parte que ninguém automatiza.

**Atualizado em:** 2026-09-06 · **71 fichas** de clientes nossos

---

## Por que isto não é automático

As 78 fichas em rascunho já têm o que dá para deduzir do Zabbix: o que o alerta
mede, sintomas, o que verificar antes de agir, riscos e ressalvas. O que falta
é o que **só vocês sabem** — e que nenhuma chave de item revela:

| Campo | Pergunta que ele responde |
|---|---|
| **Abre chamado?** | este alerta gera chamado sempre, só se persistir, ou nunca? |
| **Time** | quem resolve isso |
| **Fila** | onde o chamado é aberto (DeskManager, ServiceNow, e-mail…) |
| **Critério de resolução** | como o operador sabe que acabou |

Enquanto esses quatro estiverem vazios, a ficha **não entra na wiki** — e isso
é proposital: procedimento sem dono e sem critério de encerramento manda o
operador agir no escuro às 3h.

---

## Como preencher

```bash
python main.py serve      # abre em http://127.0.0.1:8000
```

1. **Regras** na barra lateral → filtro **Procedimento: Rascunho**
2. Clique na regra → role até **Procedimento**
3. Preencha os quatro campos, mude o estado para **Validado** e salve
4. Ao terminar um lote: `python main.py wiki` e confira o resultado

> O sistema **recusa** marcar como Validado sem os campos mínimos. Se der erro
> 422, é isso — não é bug.

### Atalho: decida por categoria, não por ficha

A maioria das fichas de uma mesma categoria vai para o mesmo time. Decidir uma
vez por categoria transforma ~70 decisões em ~15. Sugestão de ordem: resolva a
categoria inteira de uma sentada, e só volte atrás se alguma ficha destoar.

---

## Vibe Tecnologia — 52 fichas, 2.265 alertas

### Chamados e filas — 1 ficha, 1111 alertas

- [ ] **1111 alertas** — Chamados e filas de atendimento (DeskManager) sem movimentacao dentro do
  <br>`rule|vibe-tecnologia--ticket`

### Rede / Interfaces — 5 fichas, 413 alertas

- [ ] **269 alertas** — Interfaces de rede (roteador/AP) com erro, queda ou degradacao
  <br>`rule|ativos-de-rede--network_interface`
- [ ] **120 alertas** — Interfaces de Access Points Ubiquiti com erro ou degradacao
  <br>`rule|pontos-de-acesso--network_interface`
- [ ] **12 alertas** — Interfaces de rede — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--network_interface`
- [ ] **8 alertas** — Interfaces de rede — Zabbix servers
  <br>`rule|zabbix-servers--network_interface`
- [ ] **4 alertas** — Interfaces de rede — Virtual machines
  <br>`rule|virtual-machines--network_interface`

### Serviços e processos — 3 fichas, 114 alertas

- [ ] **64 alertas** — Servico do Windows/Linux parado ou perto do limite de processos
  <br>`rule|vibe-tecnologia--service`
- [ ] **48 alertas** — Serviço do Windows parado — Windows bob (VM)
  <br>`rule|virtual-machines--service`
- [ ] **2 alertas** — Servicos e limite de processos — Zabbix servers
  <br>`rule|zabbix-servers--service`

### Agente Zabbix / coleta — 5 fichas, 90 alertas

- [ ] **79 alertas** — Agente/Proxy Zabbix indisponivel ou desatualizado (Zabbix server / Zabbi
  <br>`rule|zabbix-servers--agent`
- [ ] **6 alertas** — Coleta indisponivel (agente/SNMP) — Ativos de Rede
  <br>`rule|ativos-de-rede--agent`
- [ ] **3 alertas** — Coleta indisponivel (agente/SNMP) — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--agent`
- [ ] **1 alerta** — Coleta indisponivel (agente/SNMP) — Servidores ⚠️ confiança baixa
  <br>`rule|servidores--agent`
- [ ] **1 alerta** — Coleta indisponivel (agente/SNMP) — Virtual machines
  <br>`rule|virtual-machines--agent`

### Rede / Conectividade — 5 fichas, 78 alertas

- [ ] **38 alertas** — Host/servico indisponivel por ICMP ou TCP — grupo Vibe Tecnologia
  <br>`rule|vibe-tecnologia--connectivity`
- [ ] **20 alertas** — Conectividade (ICMP/TCP) — Ativos de Rede
  <br>`rule|ativos-de-rede--connectivity`
- [ ] **8 alertas** — Conectividade (ICMP/TCP) — IOT
  <br>`rule|iot--connectivity`
- [ ] **6 alertas** — Conectividade (ICMP/TCP) — Servidores
  <br>`rule|servidores--connectivity`
- [ ] **6 alertas** — Conectividade (ICMP/TCP) — Zabbix servers
  <br>`rule|zabbix-servers--connectivity`

### Certificados e domínios — 3 fichas, 74 alertas

- [ ] **36 alertas** — Certificado/dominio proximo do vencimento ou invalido — domínios Vibe
  <br>`rule|vibe-tecnologia--certificate`
- [ ] **35 alertas** — [POSSIVEL DUPLICATA] Ver regra 'vibe-tecnologia--certificate' ⚠️ duplicata
  <br>`rule|dominios-e-certificados--certificate`
- [ ] **3 alertas** — Certificados, dominios e licencas com validade — Ativos de Rede ⚠️ confiança baixa
  <br>`rule|ativos-de-rede--certificate`

### Hardware e sensores — 3 fichas, 72 alertas

- [ ] **36 alertas** — Hardware de rede — temperatura, fonte, chassi (roteadores/APs/Fortigate)
  <br>`rule|ativos-de-rede--hardware`
- [ ] **35 alertas** — Hardware do servidor DELL (iDRAC) — temperatura, fonte, disco fisico, RA
  <br>`rule|servidores--hardware`
- [ ] **1 alerta** — Hardware e sensores — Vibe Tecnologia ⚠️ confiança baixa
  <br>`rule|vibe-tecnologia--hardware`

### Licenças — 1 ficha, 58 alertas

- [ ] **58 alertas** — Licenca Microsoft 365 em 100% de uso
  <br>`rule|vibe-tecnologia--license`

### VPN e SD-WAN — 1 ficha, 56 alertas

- [ ] **56 alertas** — Tunel VPN ou link SD-WAN degradado (Fortigate)
  <br>`rule|ativos-de-rede--vpn`

### Sistema operacional — 5 fichas, 47 alertas

- [ ] **18 alertas** — Estado do sistema operacional — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--system_state`
- [ ] **15 alertas** — Estado do sistema operacional — Zabbix servers
  <br>`rule|zabbix-servers--system_state`
- [ ] **9 alertas** — Estado do sistema operacional — Ativos de Rede
  <br>`rule|ativos-de-rede--system_state`
- [ ] **4 alertas** — Estado do sistema operacional — Virtual machines
  <br>`rule|virtual-machines--system_state`
- [ ] **1 alerta** — Estado do sistema operacional — Servidores ⚠️ confiança baixa
  <br>`rule|servidores--system_state`

### CPU / Processamento — 5 fichas, 45 alertas

- [ ] **18 alertas** — CPU / carga de processamento — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--cpu`
- [ ] **9 alertas** — CPU / carga de processamento — Virtual machines
  <br>`rule|virtual-machines--cpu`
- [ ] **7 alertas** — CPU / carga de processamento — Applications
  <br>`rule|applications--cpu`
- [ ] **7 alertas** — CPU / carga de processamento — Ativos de Rede
  <br>`rule|ativos-de-rede--cpu`
- [ ] **4 alertas** — CPU / carga de processamento — Zabbix servers
  <br>`rule|zabbix-servers--cpu`

### Disco / Filesystem — 4 fichas, 44 alertas

- [ ] **23 alertas** — Espaco em disco / filesystem — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--filesystem`
- [ ] **15 alertas** — Espaco em disco / filesystem — Zabbix servers
  <br>`rule|zabbix-servers--filesystem`
- [ ] **4 alertas** — Espaco em disco / filesystem — Ativos de Rede
  <br>`rule|ativos-de-rede--filesystem`
- [ ] **2 alertas** — Espaco em disco / filesystem — Virtual machines
  <br>`rule|virtual-machines--filesystem`

### Memória — 4 fichas, 28 alertas

- [ ] **13 alertas** — Memoria e swap — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--memory`
- [ ] **7 alertas** — Memoria e swap — Ativos de Rede
  <br>`rule|ativos-de-rede--memory`
- [ ] **6 alertas** — Memoria e swap — Zabbix servers
  <br>`rule|zabbix-servers--memory`
- [ ] **2 alertas** — Memoria e swap — Virtual machines
  <br>`rule|virtual-machines--memory`

### APIs e checagens web — 1 ficha, 13 alertas

- [ ] **13 alertas** — Endpoint web / API indisponivel ou lenta — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--api_web`

### Banco de dados — 1 ficha, 11 alertas

- [ ] **11 alertas** — Banco de dados — Zabbix servers
  <br>`rule|zabbix-servers--database`

### Disco / I-O — 2 fichas, 5 alertas

- [ ] **3 alertas** — Latencia de disco (I/O) — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--storage_io`
- [ ] **2 alertas** — Latencia de disco (I/O) — Zabbix servers
  <br>`rule|zabbix-servers--storage_io`

### Segurança e integridade — 2 fichas, 4 alertas

- [ ] **2 alertas** — Integridade de arquivo de sistema — Vibe Tecnologia
  <br>`rule|vibe-tecnologia--security`
- [ ] **2 alertas** — Integridade de arquivo de sistema — Zabbix servers
  <br>`rule|zabbix-servers--security`

### Nuvem — 1 ficha, 2 alertas

- [ ] **2 alertas** — Recursos em nuvem — Vibe Tecnologia ⚠️ confiança baixa
  <br>`rule|vibe-tecnologia--cloud`

---

## Chubb — 15 fichas, 16.543 alertas

### Jobs e agendamentos — 1 ficha, 16479 alertas

- [ ] **16479 alertas** — [DUPLICATA DE ESCOPO] Ver regra 'control-m-in01--job' ⚠️ duplicata
  <br>`rule|applications--job`

### Banco de dados — 1 ficha, 37 alertas

- [ ] **37 alertas** — Banco de dados Azure SQL — Chubb (CPU, locks, backup, tamanho)
  <br>`rule|cliente-chubb--database`

### Rede / Conectividade — 1 ficha, 12 alertas

- [ ] **12 alertas** — Conectividade (ICMP/TCP) — Cliente_chubb
  <br>`rule|cliente-chubb--connectivity`

### Alertas específicos — 10 fichas, 10 alertas

- [ ] **1 alerta** — Arquivo de integracao ENEL nao gerado / gerado em branco
  <br>`lld|chubb-links-de-api|autorization-enel-api|arquivo-em-branco-api-com-dados-reprocessar-rec`
- [ ] **1 alerta** — Arquivo de integracao ENEL nao gerado / gerado em branco
  <br>`lld|chubb-links-de-api|autorization-enel-api|arquivo-em-branco-api-com-dados-reprocessar`
- [ ] **1 alerta** — Arquivo de integracao ENEL nao gerado / gerado em branco
  <br>`lld|chubb-links-de-api|autorization-enel-api|arquivo-gerado-em-branco`
- [ ] **1 alerta** — Arquivo de integracao ENEL nao gerado / gerado em branco
  <br>`lld|chubb-links-de-api|autorization-enel-api|arquivo-nao-gerado-rec`
- [ ] **1 alerta** — Arquivo de integracao ENEL nao gerado / gerado em branco
  <br>`lld|chubb-links-de-api|autorization-enel-api|arquivo-nao-gerado`
- [ ] **1 alerta** — API - Vibe (processamento) indisponivel — SEM PROCEDIMENTO NO MANUAL
  <br>`rule|api-vibe-processamento-indisponivel|1fa51970`
- [ ] **1 alerta** — FTP Chubb Indisponivel (https://mft.chubblatinamerica.com:9443/Login) — 
  <br>`rule|ftp-chubb-indisponivel-https-mft-chubblatinamerica-com-9443-login|2c72393c`
- [ ] **1 alerta** — FTP Chubb Indisponivel — SEM PROCEDIMENTO NO MANUAL
  <br>`rule|ftp-chubb-indisponivel|4c85fe4b`
- [ ] **1 alerta** — FTP Chubb (ultimo upload) a mais de 24h — SEM PROCEDIMENTO NO MANUAL
  <br>`rule|ftp-chubb-ultimo-upload-a-mais-de-24h|f6d708cf`
- [ ] **1 alerta** — SSH Chubb Indisponivel (http://mft.chubblatinamerica.com:1224) — SEM PRO
  <br>`rule|ssh-chubb-indisponivel-http-mft-chubblatinamerica-com-1224|cd4ecfe6`

### APIs e checagens web — 1 ficha, 4 alertas

- [ ] **4 alertas** — Endpoint web / API indisponivel ou lenta — Cliente_chubb
  <br>`rule|cliente-chubb--api_web`

### CPU / Processamento — 1 ficha, 1 alerta

- [ ] **1 alerta** — CPU / carga de processamento — Cliente_chubb ⚠️ confiança baixa
  <br>`rule|cliente-chubb--cpu`

---

## SAQ (pagamentos) — 4 fichas, 91 alertas

### Nuvem — 1 ficha, 57 alertas

- [ ] **57 alertas** — Falha em funcao Lambda / recurso AWS (Saq)
  <br>`rule|saq--cloud`

### Certificados e domínios — 1 ficha, 25 alertas

- [ ] **25 alertas** — Certificado/dominio SAQ proximo do vencimento ou invalido
  <br>`rule|saq-certificados--certificate`

### APIs e checagens web — 1 ficha, 7 alertas

- [ ] **7 alertas** — Endpoint web / API indisponivel ou lenta — Saq
  <br>`rule|saq--api_web`

### Rede / Conectividade — 1 ficha, 2 alertas

- [ ] **2 alertas** — Conectividade (ICMP/TCP) — Saq
  <br>`rule|saq--connectivity`

---

## Fora da wiki — 7 fichas de clientes de outro NOC

Estas existem na base mas **não entram na wiki gerada**, porque o atendimento
é de outro NOC. Só preencha se decidirem assumir esses clientes.

- [ ] 44 alertas — Carguero — API indisponivel/lenta — Carguero (monitor de APIs)
- [ ] 34 alertas — Pagol — APIGateway com erro/latencia — Pagol/Bankeiro (Grafana)
- [ ] 14 alertas — Banpará — Perda de pacotes no roteador de link (Interconnect, Oi ou EB
- [ ] 7 alertas — Hocta — Endpoint web / API indisponivel ou lenta — Cliente_Hocta
- [ ] 4 alertas — Pagol — Servicos e limite de processos — Applications
- [ ] 2 alertas — Banpará — Conectividade (ICMP/TCP) — Cliente_Bapara
- [ ] 1 alerta — Banpará — Endpoint web / API indisponivel ou lenta — Banpara

---

## Depois dos rascunhos: a cauda longa

Sobram **451 fichas** sem procedimento nenhum. Elas não têm nem o rascunho
técnico, e a maioria é de baixo volume.

**Não recomendo atacar de frente.** O caminho mais barato:

1. Termine os rascunhos acima — eles cobrem os alertas de maior volume
2. Rode `python main.py serve` → **Procedimentos** → filtre **Ausente**
3. Ordene por quantidade de alertas e vá de cima para baixo
4. O que for alerta de teste ou ruído, marque **Não aplicável** em vez de
   documentar — sai da fila e para de contar como dívida

---

## Como medir o progresso

```bash
python main.py status    # cobertura: validadas / que precisam de procedimento
python main.py wiki      # quantos procedimentos entraram, e por cliente
```

Ponto de partida (2026-09-06): **51 validadas de 580**, wiki com 41
procedimentos em 4 clientes.

Marque os itens aqui conforme concluir — e me avise para eu regenerar a wiki e
atualizar o [CHECKLIST.md](CHECKLIST.md).
