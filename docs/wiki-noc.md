# 📘 Catálogo de Alertas — NOC

Guia operacional para **triagem, abertura de chamado e acionamento correto**
dos alertas monitorados. Cada categoria traz uma tabela de ação rápida, a
referência técnica completa e o procedimento detalhado.

> **Regra de ouro:** nenhum acionamento por Teams ou telefone acontece sem
> **chamado aberto** e **evidência coletada** (host, horário, print/output).
> O SLA só começa a contar depois do chamado registrado.
{.is-warning}

> **Esta página é gerada.** O conteúdo vem das fichas validadas em
> `docs/alerts/` do repositório Zabbix-Wiki — não edite aqui, edite a ficha e
> gere de novo (`python main.py wiki`). Assim a página nunca diverge do que o
> time aprovou, e envelhece junto com o Zabbix em vez de envelhecer sozinha.
{.is-info}

## ⚡ Fluxo de atendimento

```mermaid
flowchart TD
    A["🔔 Alerta recebido"] --> B{"Severidade"}
    B -->|"🔵 Baixa / 🟡 Média"| C["Aguardar a tolerância do alerta"]
    B -->|"🟠 Alta / 🔴 Crítica"| D["Validar imediatamente"]
    C --> E{"Normalizou sozinho?"}
    E -->|"Sim"| F["Registrar no plantão e encerrar"]
    E -->|"Não"| D
    D --> G["Coletar evidências<br/>host, data e hora, print, output"]
    G --> H["Abrir chamado no DeskManager"]
    H --> I["Transferir para a fila responsável"]
    I --> J{"Houve retorno dentro do SLA?"}
    J -->|"Sim"| K["Acompanhar até a normalização"]
    J -->|"Não"| L["Escalonar<br/>Teams ou telefone do sobreaviso"]
```

## 🎚️ Severidade

| Ícone | Severidade | Postura esperada |
| :---: | :--- | :--- |
| 🔴 | **Crítica** (Disaster) | Validar e abrir chamado na hora. Comunicar o plantão. |
| 🟠 | **Alta** (High) | Validar e abrir chamado na hora. |
| 🟡 | **Média** (Average/Warning) | Respeitar a tolerância do alerta antes de abrir. |
| 🔵 | **Baixa** (Information) | Registrar e transferir sem urgência. |

> **Como ler o SLA:** `7 min` é o tempo de tolerância **mais** a espera pelo
> retorno do chamado antes de escalonar. `Imediato` significa abrir o chamado
> assim que o alerta for validado.
{.is-info}

## 🏢 Clientes

| Cliente | Procedimentos | Alertas | Hosts |
| :--- | ---: | ---: | ---: |
| **Vibe Tecnologia** | 26 | 26 | 9 |
| **Chubb** | 3 | 10 | 2 |
| **Master Support (interno)** | 6 | 6 | 1 |
| **Votorantim** | 6 | 6 | 2 |

## 📋 Catálogo por cliente {.tabset}

### Vibe Tecnologia

**26 alerta(s)** em 26 procedimento(s) · 9 host(s): `Embratel - Roteador [Cisco]`, `Interconect - Roteador`, `Vibe - AP REUNIAO [Ubiquiti]`, `Vibe - Ferramentas Internas`, `Vibe - Impressora [HP]`, `Vibe - MSTracker-vm Hom`, `Vibe - Proxy [Fortigate]`, `Vibe - Wazuh SIEM` e mais 1

> Vem por último entre os monitorados: o host group 'Vibe Tecnologia' é usado como guarda-chuva de infraestrutura compartilhada (links de operadora, câmeras, servidores sem prefixo).
{.is-info}

#### ☎️ Acionamento

| Fila / Time | Canal | Escalonamento | Alertas cobertos |
| :--- | :--- | :--- | ---: |
| **Administrativo** | DeskManager · E-mail | — | 4 |
| **Carlos Favacho** | DeskManager | Carlos Favacho | 1 |
| **Infraestrutura** | DeskManager | Rafael Sales | 7 |
| **NOC / GE** | Central de Servicos | — | 5 |
| **NOC / Infra** | DeskManager | — | 1 |
| **NOC → operadora** | Desk Manager (com o protocolo da operadora) | líderes + NOC · líderes + NOC (e-mail com protocolo) | 4 |
| **RH** | DeskManager | — | 2 |
| **Suporte Oracle** | DeskManager | — | 2 |

#### Rede / Conectividade

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Alta perda de pacotes ICMP — AP REUNIAO | 🟡 | Vibe - AP REUNIAO [Ubiquiti] | Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales). | Infraestrutura · DeskManager | ⏱️ 5 min |
| Impressora HP inacessivel (ICMP) | 🟡 | Vibe - Impressora [HP] | Verificar presencialmente na fabrica e abrir chamado. | NOC / GE · Central de Servicos | ⏱️ Imediato |
| Link PRINCIPAL da fábrica (Embratel) indisponível | 🔴 | Embratel - Roteador [Cisco] | Acionar a Embratel pelo portal WebSIR com o código de designação, ou pelo 0800 721 1021 / caebt@claroatendimento.com.br | NOC → operadora · Desk Manager (com o protocolo da operadora) | ⏱️ Imediato |
| Link de BACKUP da fábrica (Interconnect/Vellon) indisponível | 🔴 | Interconect - Roteador | Acionar a Vellon Telecom por WhatsApp (+55 91 99264-4565): opção 1 → 1 (sou cliente) → CNPJ 13956365000136 → 1 → 1 → aguardar operador | NOC → operadora · Desk Manager (com o protocolo da operadora) | ⏱️ Imediato |
| Link de BACKUP da fábrica (Interconnect/Vellon) indisponível — visto pelo Embratel | 🔴 | Embratel - Roteador [Cisco] | Acionar a Vellon Telecom por WhatsApp (+55 91 99264-4565): opção 1 → 1 (sou cliente) → CNPJ 13956365000136 → 1 → 1 → aguardar operador | NOC → operadora · Desk Manager (com o protocolo da operadora) | ⏱️ Imediato |
| Roteador Embratel inalcançável (ICMP) | 🟠 | Embratel - Roteador [Cisco] | Acionar a Embratel (portal WebSIR com a designação, ou 0800 721 1021) | NOC → operadora · Desk Manager (com o protocolo da operadora) | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Rede / Conectividade</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Alta perda de pacotes ICMP — AP REUNIAO | Perda de pacotes na comunicacao com o AP. | Intermitencia wireless (AirOS). | — |
| Impressora HP inacessivel (ICMP) | Impressora inacessivel na rede da fabrica. | Equipamento desligado ou falha de rede. | Verificar presencialmente na fabrica |
| Link PRINCIPAL da fábrica (Embratel) indisponível | Host 'Embratel - Roteador [Cisco]'. É o link PRINCIPAL da fábrica. Com ele fora, a operação depende do link de backup (Interconnect/Vellon) — se os dois caírem, a fábrica fica sem conectividade. | Falha do circuito da operadora, equipamento no local, ou rompimento. | Verificar o aparelho preto no local: lâmpada PON verde = conexão OK; lâmpada SD vermelha = rede instável · Confirmar se o link de backup (Interconnect) assumiu |
| Link de BACKUP da fábrica (Interconnect/Vellon) indisponível | Alerta no próprio host 'Interconect - Roteador'. É o link de BACKUP da fábrica; o principal é a Embratel. | Falha do circuito da Vellon/Interconnect ou do equipamento no local. | Confirmar que o link principal (Embratel) segue operando |
| Link de BACKUP da fábrica (Interconnect/Vellon) indisponível — visto pelo Embratel | Alerta no host 'Embratel - Roteador [Cisco]' sinalizando que o link de BACKUP (Interconnect/Vellon) está fora. Sozinho não derruba a operação — mas deixa a fábrica sem redundância. | Falha do circuito da Vellon/Interconnect ou do equipamento no local. | Confirmar que o link principal (Embratel) segue operando |
| Roteador Embratel inalcançável (ICMP) | Host 'Embratel - Roteador [Cisco]' não responde a ping — pode ser queda do link ou do equipamento. | Queda do circuito, do equipamento no local, ou falta de energia. | Verificar as lâmpadas do aparelho preto no local (PON verde = OK, SD vermelha = instável) · Confirmar se o alerta de 'Link Principal indisponível' também disparou |

</details>

##### 🟡 Alta perda de pacotes ICMP — AP REUNIAO

**Sintomas:**
* 'Ubiquiti AirOS: High ICMP ping loss' no host Vibe - AP REUNIAO Ubiquiti

**Ações:**
* Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales).

**Critério de resolução:** Perda de pacotes volta ao normal.

**Observações:** Severidade: Media. SLA: 7 min (5m tolerancia + 2m espera de retorno do chamado). Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🟡 Impressora HP inacessivel (ICMP)

**Sintomas:**
* 'ICMP: Unavailable by ICMP ping' no host Vibe - Impressora HP

**Verificações antes de agir:**
* Verificar presencialmente na fabrica

**Ações:**
* Verificar presencialmente na fabrica e abrir chamado.

**Critério de resolução:** Impressora volta a responder ao ping.

**Observações:** Severidade: Alta. SLA: Imediato. Horario: NOC/GE atende 24x7. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🔴 Link PRINCIPAL da fábrica (Embratel) indisponível

Restabelecer o link principal da fábrica acionando a Embratel.

**Sintomas:**
* 'Link Principal - Fábrica Embratel indisponível' (Disaster)

**Verificações antes de agir:**
* Verificar o aparelho preto no local: lâmpada PON verde = conexão OK; lâmpada SD vermelha = rede instável
* Confirmar se o link de backup (Interconnect) assumiu

**Ações:**
* Acionar a Embratel pelo portal WebSIR com o código de designação, ou pelo 0800 721 1021 / caebt@claroatendimento.com.br
* Informar +55 91 3222-1678 (NOC) como telefone de contato do chamado
* Formalizar por e-mail para líderes e NOC, com o erro e o protocolo
* Abrir chamado no Desk Manager por integração, com o protocolo da operadora

**Riscos e ressalvas:**
* Se o backup também estiver fora, a fábrica está sem conectividade — tratar como indisponibilidade total, não como queda de um link.

**Critério de resolução:** Link principal volta a responder e a operadora confirma o restabelecimento.

**Observações:** Wiki de rede do NOC (acionamento de operadoras), repassada pelo time em 2026-09-06. EMBRATEL (link principal) — Antes de abrir chamado, verificar o aparelho: no primeiro equipamento (preto), lâmpada PON verde = conexão estável; lâmpada SD vermelha = rede instável. Abertura pelo portal WebSIR (link com a designação na wiki de rede), ou 0800 721 1021 / caebt@claroatendimento.com.br. Informar o telefone do NOC como contato: +55 91 3222-1678. Depois formalizar por e-mail (erro + protocolo) para os líderes e o NOC, e abrir chamado no Desk Manager por integração com o protocolo.

**Evidências obrigatórias no chamado:** Protocolo da Embratel · Estado das lâmpadas do aparelho (PON/SD)

##### 🔴 Link de BACKUP da fábrica (Interconnect/Vellon) indisponível

Restabelecer o link de backup antes que o principal também falhe.

**Sintomas:**
* 'Link Backup - Fábrica Interconnect indisponível' (Disaster)

**Verificações antes de agir:**
* Confirmar que o link principal (Embratel) segue operando

**Ações:**
* Acionar a Vellon Telecom por WhatsApp (+55 91 99264-4565): opção 1 → 1 (sou cliente) → CNPJ 13956365000136 → 1 → 1 → aguardar operador
* Formalizar por e-mail para líderes e NOC com o protocolo
* Abrir chamado no Desk Manager com o protocolo

**Riscos e ressalvas:**
* Este alerta e o do host Embratel apontam o MESMO link de backup, por caminhos diferentes. Dois alertas, um incidente — não abrir dois chamados.

**Critério de resolução:** Link de backup volta a responder.

**Observações:** Wiki de rede do NOC (acionamento de operadoras), repassada pelo time em 2026-09-06. VELLON TELECOM / INTERCONNECT (link de backup) — Atendimento por WhatsApp: +55 91 99264-4565. Sequência: opção 1 → opção 1 (sou cliente) → CNPJ 13956365000136 → opção 1 → opção 1 → aguardar operador. Formalizar por e-mail para líderes e NOC, e abrir chamado no Desk Manager com o protocolo.

**Evidências obrigatórias no chamado:** Protocolo da Vellon · Estado do link principal no momento

##### 🔴 Link de BACKUP da fábrica (Interconnect/Vellon) indisponível — visto pelo Embratel

Restabelecer o link de backup antes que o principal também falhe.

**Sintomas:**
* 'Link Backup - Fábrica Interconnect indisponível' (Disaster)

**Verificações antes de agir:**
* Confirmar que o link principal (Embratel) segue operando

**Ações:**
* Acionar a Vellon Telecom por WhatsApp (+55 91 99264-4565): opção 1 → 1 (sou cliente) → CNPJ 13956365000136 → 1 → 1 → aguardar operador
* Formalizar por e-mail para líderes e NOC com o protocolo
* Abrir chamado no Desk Manager com o protocolo

**Riscos e ressalvas:**
* Severidade Disaster, mas sem impacto imediato SE o principal estiver de pé: o risco é ficar sem redundância. Confirmar o estado do principal antes de classificar a urgência.

**Critério de resolução:** Link de backup volta a responder e a redundância é restabelecida.

**Observações:** Wiki de rede do NOC (acionamento de operadoras), repassada pelo time em 2026-09-06. VELLON TELECOM / INTERCONNECT (link de backup) — Atendimento por WhatsApp: +55 91 99264-4565. Sequência: opção 1 → opção 1 (sou cliente) → CNPJ 13956365000136 → opção 1 → opção 1 → aguardar operador. Formalizar por e-mail para líderes e NOC, e abrir chamado no Desk Manager com o protocolo.

**Evidências obrigatórias no chamado:** Protocolo da Vellon · Estado do link principal no momento

##### 🟠 Roteador Embratel inalcançável (ICMP)

Confirmar se o roteador do link principal está fora antes de acionar a operadora.

**Sintomas:**
* 'Cisco IOS: Unavailable by ICMP ping' (High)

**Verificações antes de agir:**
* Verificar as lâmpadas do aparelho preto no local (PON verde = OK, SD vermelha = instável)
* Confirmar se o alerta de 'Link Principal indisponível' também disparou

**Ações:**
* Acionar a Embratel (portal WebSIR com a designação, ou 0800 721 1021)
* Informar +55 91 3222-1678 (NOC) como contato
* Formalizar por e-mail e abrir no Desk Manager com o protocolo

**Riscos e ressalvas:**
* Costuma vir junto com 'Link Principal indisponível' — é o mesmo incidente.

**Critério de resolução:** Roteador volta a responder ao ping.

**Observações:** Wiki de rede do NOC (acionamento de operadoras), repassada pelo time em 2026-09-06. EMBRATEL (link principal) — Antes de abrir chamado, verificar o aparelho: no primeiro equipamento (preto), lâmpada PON verde = conexão estável; lâmpada SD vermelha = rede instável. Abertura pelo portal WebSIR (link com a designação na wiki de rede), ou 0800 721 1021 / caebt@claroatendimento.com.br. Informar o telefone do NOC como contato: +55 91 3222-1678. Depois formalizar por e-mail (erro + protocolo) para os líderes e o NOC, e abrir chamado no Desk Manager por integração com o protocolo.

#### Rede / Interfaces

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| VPNBKP com baixo trafego (Proxy Fortigate) | 🟡 | Vibe - Proxy [Fortigate] | Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales). | Infraestrutura · DeskManager | ⏱️ 5 min |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Rede / Interfaces</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| VPNBKP com baixo trafego (Proxy Fortigate) | Trafego abaixo do normal na VPN de backup. | Intermitencia IPsec. | — |

</details>

##### 🟡 VPNBKP com baixo trafego (Proxy Fortigate)

**Sintomas:**
* 'Interface VPNBKP(): Baixo Trafego' no host Vibe - Proxy Fortigate

**Ações:**
* Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales).

**Critério de resolução:** Trafego da VPN de backup volta ao patamar normal.

**Observações:** Severidade: Media. SLA: 7 min (5m + 2m). SLA MAIS ESPECIFICO que o da regra 'Rede / Interfaces' do grupo Ativos de Rede (12 min) -- esta ficha prevalece para esta interface especifica. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

#### Disco / Filesystem

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Disco (/) acima de 80% no Wazuh SIEM | 🟡 | Vibe - Wazuh SIEM | Abrir chamado informando o alerta e o host afetado. | Infraestrutura · DeskManager | ⏱️ Imediato |
| Disco critico (/) no Zabbix-Proxy | 🟡 | Vibe - Zabbix-Proxy | Abrir ou transferir chamado solicitando liberacao de espaco. | Infraestrutura · DeskManager | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Disco / Filesystem</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Disco (/) acima de 80% no Wazuh SIEM | Espaco da particao raiz (/) acima de 80%. | Geracao excessiva de logs pelo firewall. | Checar volume de logs recentes no SIEM |
| Disco critico (/) no Zabbix-Proxy | Espaco da particao raiz em nivel critico. Tende a durar dias ate a intervencao. | Crescimento de logs ou arquivos temporarios. | Confirmar o percentual livre atual no host |

</details>

##### 🟡 Disco (/) acima de 80% no Wazuh SIEM

**Sintomas:**
* '/: Disk space is low (used > 80%)' no host Vibe - Wazuh SIEM

**Verificações antes de agir:**
* Checar volume de logs recentes no SIEM

**Ações:**
* Abrir chamado informando o alerta e o host afetado.

**Critério de resolução:** Uso volta a ficar abaixo de 80%.

**Observações:** Severidade: Media. SLA: Imediato. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🟡 Disco critico (/) no Zabbix-Proxy

**Sintomas:**
* '/: Disk space is critically low' no host Vibe - Zabbix-Proxy

**Verificações antes de agir:**
* Confirmar o percentual livre atual no host

**Ações:**
* Abrir ou transferir chamado solicitando liberacao de espaco.

**Critério de resolução:** Espaco livre volta a ficar acima do limite critico configurado no trigger.

**Observações:** Severidade: Critica. SLA: Imediato. Ref. chamado 0726-001673 (caso anterior). Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

#### Disco / Desempenho de I-O

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Disco (sda) com tempo de resposta alto no Zabbix-Proxy | 🟡 | Vibe - Zabbix-Proxy | Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales). | Infraestrutura · DeskManager | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Disco / Desempenho de I-O</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Disco (sda) com tempo de resposta alto no Zabbix-Proxy | Tempo de espera (await) muito alto no disco do servidor. | Gargalo de I/O no disco. | Verificar uso de I/O e processos consumindo disco no host |

</details>

##### 🟡 Disco (sda) com tempo de resposta alto no Zabbix-Proxy

**Sintomas:**
* 'sda: Disk read/write request responses are too high' no host Vibe - Zabbix-Proxy

**Verificações antes de agir:**
* Verificar uso de I/O e processos consumindo disco no host

**Ações:**
* Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales).

**Critério de resolução:** Tempo de resposta do disco volta ao normal.

**Observações:** Severidade: Alta. SLA: Imediato. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

#### Agente Zabbix

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Zabbix agent indisponivel no Wazuh SIEM | 🟡 | Vibe - MSTracker-vm Hom | Transferir para a Infraestrutura (chamado teste do setor). | NOC / Infra · DeskManager | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Agente Zabbix</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Zabbix agent indisponivel no Wazuh SIEM | Agente Zabbix parado ou host indisponivel (mensagem padrao inclui aviso sobre agentes passive-only). | Falha de rede ou porta 10050 bloqueada. | Confirmar se e chamado teste do setor antes de escalar |

</details>

##### 🟡 Zabbix agent indisponivel no Wazuh SIEM

**Sintomas:**
* 'Linux: Zabbix agent is not available' no host Vibe - Wazuh SIEM

**Verificações antes de agir:**
* Confirmar se e chamado teste do setor antes de escalar

**Ações:**
* Transferir para a Infraestrutura (chamado teste do setor).

**Critério de resolução:** Agente volta a responder / host volta a 'monitored'.

**Observações:** Severidade: Media. SLA: Imediato. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

#### APIs e checagens web

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Instabilidade na plataforma Feedz | 🔴 | Vibe - Ferramentas Internas | Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales). | Infraestrutura · DeskManager | ⏱️ Imediato |
| Instabilidade na plataforma Feedz (falha de step do cenario web) | 🔴 | Vibe - Ferramentas Internas | Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales). | Infraestrutura · DeskManager | ⏱️ Imediato |
| Instabilidade no Portal RH Cloud | 🔴 | Vibe - Ferramentas Internas | Reportar a instabilidade do Portal. | Carlos Favacho · DeskManager | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — APIs e checagens web</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Instabilidade na plataforma Feedz | Instabilidade na plataforma Feedz. | Falha de conexao externa. | — |
| Instabilidade na plataforma Feedz (falha de step do cenario web) | Instabilidade na plataforma Feedz. | Falha de conexao externa. | — |
| Instabilidade no Portal RH Cloud | Erro na resposta HTTP do Portal RH Cloud. | Causa nao informada na fonte original — investigar na ocorrencia. | — |

</details>

##### 🔴 Instabilidade na plataforma Feedz

**Sintomas:**
* 'Http response - Feedz' no host Vibe - Ferramentas Internas

**Ações:**
* Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales).

**Critério de resolução:** Cenario web volta a responder com sucesso.

**Observações:** Severidade: Media. SLA: Imediato. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🔴 Instabilidade na plataforma Feedz (falha de step do cenario web)

**Sintomas:**
* 'Failed step of scenario "Http Response - Feedz".' no host Vibe - Ferramentas Internas

**Ações:**
* Abrir chamado. Sem resposta, acionar no Teams (Rafael Sales).

**Critério de resolução:** Cenario web volta a responder com sucesso.

**Observações:** Severidade: Media. SLA: Imediato. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🔴 Instabilidade no Portal RH Cloud

**Sintomas:**
* 'Http Response - Portal RH Cloud' no host Vibe - Ferramentas Internas

**Ações:**
* Reportar a instabilidade do Portal.

**Critério de resolução:** Portal volta a responder com HTTP 200.

**Observações:** Severidade: Media. SLA: Imediato. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

#### Outros

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Toner Amarelo abaixo de 5% (Impressora HP) | 🟡 | Vibe - Impressora [HP] | Solicitar substituicao e fazer teste de impressao apos a troca. | NOC / GE · Central de Servicos | ⏱️ Imediato |
| Toner Ciano abaixo de 5% (Impressora HP) | 🟡 | Vibe - Impressora [HP] | Solicitar substituicao e fazer teste de impressao apos a troca. | NOC / GE · Central de Servicos | ⏱️ Imediato |
| Toner Magenta abaixo de 5% (Impressora HP) | 🟡 | Vibe - Impressora [HP] | Solicitar substituicao e fazer teste de impressao apos a troca. | NOC / GE · Central de Servicos | ⏱️ Imediato |
| Toner Preto abaixo de 5% (Impressora HP) | 🟡 | Vibe - Impressora [HP] | Solicitar substituicao e fazer teste de impressao apos a troca. | NOC / GE · Central de Servicos | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Outros</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Toner Amarelo abaixo de 5% (Impressora HP) | Baixa qualidade de impressao por falta de suprimento (toner magenta). | Fim da vida util do toner. | — |
| Toner Ciano abaixo de 5% (Impressora HP) | Baixa qualidade de impressao por falta de suprimento (toner magenta). | Fim da vida util do toner. | — |
| Toner Magenta abaixo de 5% (Impressora HP) | Baixa qualidade de impressao por falta de suprimento (toner magenta). | Fim da vida util do toner. | — |
| Toner Preto abaixo de 5% (Impressora HP) | Baixa qualidade de impressao por falta de suprimento (toner magenta). | Fim da vida util do toner. | — |

</details>

##### 🟡 Toner Amarelo abaixo de 5% (Impressora HP)

**Sintomas:**
* 'Toner Amarelo abaixo de 5%' no host Vibe - Impressora HP

**Ações:**
* Solicitar substituicao e fazer teste de impressao apos a troca.

**Critério de resolução:** Teste de impressao apos a troca sai correto.

**Observações:** Severidade: Baixa. SLA: Imediato. Mesmo procedimento vale para as 3 outras cores (ver fichas irmas). Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🟡 Toner Ciano abaixo de 5% (Impressora HP)

**Sintomas:**
* 'Toner Ciano abaixo de 5%' no host Vibe - Impressora HP

**Ações:**
* Solicitar substituicao e fazer teste de impressao apos a troca.

**Critério de resolução:** Teste de impressao apos a troca sai correto.

**Observações:** Severidade: Baixa. SLA: Imediato. Mesmo procedimento vale para as 3 outras cores (ver fichas irmas). Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🟡 Toner Magenta abaixo de 5% (Impressora HP)

**Sintomas:**
* 'Toner Magenta abaixo de 5%' no host Vibe - Impressora HP

**Ações:**
* Solicitar substituicao e fazer teste de impressao apos a troca.

**Critério de resolução:** Teste de impressao apos a troca sai correto.

**Observações:** Severidade: Baixa. SLA: Imediato. Mesmo procedimento vale para as 3 outras cores (ver fichas irmas). Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🟡 Toner Preto abaixo de 5% (Impressora HP)

**Sintomas:**
* 'Toner Preto abaixo de 5%' no host Vibe - Impressora HP

**Ações:**
* Solicitar substituicao e fazer teste de impressao apos a troca.

**Critério de resolução:** Teste de impressao apos a troca sai correto.

**Observações:** Severidade: Baixa. SLA: Imediato. Mesmo procedimento vale para as 3 outras cores (ver fichas irmas). Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

#### Fora do Zabbix

> Estes alertas **não vêm do Zabbix**: quem avisa é o próprio sistema de origem, por e-mail ou webhook. Não espere encontrá-los no painel.
{.is-warning}

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| RH Cloud — BeneficioNaoDisponibilizado | ⚪ | fora do Zabbix | Criar chamado reportando a falha de integracao e transferir. | RH · DeskManager | ⏱️ Imediato |
| RH Cloud — CargaComFalha | ⚪ | fora do Zabbix | Transferir chamado informando o erro. | Suporte Oracle · DeskManager | ⏱️ Imediato |
| RH Cloud — CentroDeCustoIncompleto | ⚪ | fora do Zabbix | Transferir chamado para o setor competente. | Administrativo · DeskManager | ⏱️ Imediato |
| RH Cloud — ColaboradorNaoAtivado | ⚪ | fora do Zabbix | Transferir chamado informando a matricula afetada. | RH · DeskManager | ⏱️ Imediato |
| RH Cloud — PagamentoNaoConciliado | ⚪ | fora do Zabbix | Transferir chamado relatando a divergencia. | Administrativo · DeskManager | ⏱️ Imediato |
| RH Cloud — PagamentoNaoProcessado | ⚪ | fora do Zabbix | Transferir chamado relatando o erro sistemico. | Administrativo · DeskManager | ⏱️ Imediato |
| RH Cloud — PagamentoNegativo | ⚪ | fora do Zabbix | Enviar e-mail para o setor e buscar historico de casos similares. | Administrativo · E-mail | ⏱️ — |
| RH Cloud — RotinaComFalha | ⚪ | fora do Zabbix | Se o erro mudar numa reexecucao, nao abrir chamado duplicado: vincular ao chamado existente ou abrir novo apenas se for inedito. | Suporte Oracle · DeskManager | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Fora do Zabbix</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| RH Cloud — BeneficioNaoDisponibilizado | Beneficio do funcionario nao foi disponibilizado. | Causa desconhecida (falha de integracao). | — |
| RH Cloud — CargaComFalha | Falha de carga sistemica no RH Cloud. | Erros diversos do sistema. | — |
| RH Cloud — CentroDeCustoIncompleto | Colaborador com centro de custo em 0%. | Cadastro incompleto. | — |
| RH Cloud — ColaboradorNaoAtivado | Contratacao iniciada, mas o perfil segue inativo. | Fluxo de ativacao travado. | — |
| RH Cloud — PagamentoNaoConciliado | Falha na conciliacao dos valores de pagamento. | Causa desconhecida. | — |
| RH Cloud — PagamentoNaoProcessado | Falha sistemica no fluxo de pagamento. | Causa desconhecida. | — |
| RH Cloud — PagamentoNegativo | Contracheque com saldo negativo. | Erro de calculo. | — |
| RH Cloud — RotinaComFalha | Falha na execucao de uma rotina do RH Cloud. | Erros diversos do sistema. | — |

</details>

##### ⚪ RH Cloud — BeneficioNaoDisponibilizado

**Sintomas:**
* Notificacao 'BeneficioNaoDisponibilizado' do RH Cloud

**Ações:**
* Criar chamado reportando a falha de integracao e transferir.

**Critério de resolução:** Beneficio disponibilizado ao colaborador.

**Observações:** Severidade: Media. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ RH Cloud — CargaComFalha

**Sintomas:**
* Notificacao 'CargaComFalha' do RH Cloud

**Ações:**
* Transferir chamado informando o erro.

**Critério de resolução:** Carga volta a processar com sucesso.

**Observações:** Severidade: Alta. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ RH Cloud — CentroDeCustoIncompleto

**Sintomas:**
* Notificacao 'CentroDeCustoIncompleto' do RH Cloud

**Ações:**
* Transferir chamado para o setor competente.

**Critério de resolução:** Centro de custo preenchido corretamente.

**Observações:** Severidade: Baixa. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ RH Cloud — ColaboradorNaoAtivado

**Sintomas:**
* Notificacao 'ColaboradorNaoAtivado' do RH Cloud

**Ações:**
* Transferir chamado informando a matricula afetada.

**Critério de resolução:** Perfil do colaborador ativado.

**Observações:** Severidade: Media. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ RH Cloud — PagamentoNaoConciliado

**Sintomas:**
* Notificacao 'PagamentoNaoConciliado' do RH Cloud

**Ações:**
* Transferir chamado relatando a divergencia.

**Critério de resolução:** Valores conciliados.

**Observações:** Severidade: Alta. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ RH Cloud — PagamentoNaoProcessado

**Sintomas:**
* Notificacao 'PagamentoNaoProcessado' do RH Cloud

**Ações:**
* Transferir chamado relatando o erro sistemico.

**Critério de resolução:** Pagamento processado com sucesso.

**Observações:** Severidade: Alta. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ RH Cloud — PagamentoNegativo

**Sintomas:**
* Notificacao 'PagamentoNegativo' do RH Cloud

**Ações:**
* Enviar e-mail para o setor e buscar historico de casos similares.

**Critério de resolução:** Saldo do contracheque corrigido/confirmado pelo setor.

**Observações:** Severidade: Alta. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ RH Cloud — RotinaComFalha

**Sintomas:**
* Notificacao 'RotinaComFalha' do RH Cloud

**Ações:**
* Se o erro mudar numa reexecucao, nao abrir chamado duplicado: vincular ao chamado existente ou abrir novo apenas se for inedito.

**Critério de resolução:** Rotina volta a executar com sucesso.

**Observações:** Severidade: Alta. SLA: Imediato. Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

### Chubb

**10 alerta(s)** em 3 procedimento(s) · 2 host(s): `Chubb - Links de API`, `Control-M server [IN01]`

> Inclui a plataforma Control-M SaaS (IN01 e SaaS Master), confirmada como dedicada à Chubb, e a Azure Function do App Enel.
{.is-info}

#### ☎️ Acionamento

| Fila / Time | Canal | Escalonamento | Alertas cobertos |
| :--- | :--- | :--- | ---: |
| **NOC** | e-mail para contatos Chubb | Mayara Polonio, Gabriel Chakrian, Jajyta Biadolla, Priscila Costa (Chubb) — copiar João Queiroz (Vibe) | 9 |
| **Suporte Oracle (procedure iniciou e falhou) ou Suporte BMC (falha do Control-M/integracao)** | DeskManager | — | 1 |

#### Rede / Conectividade

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| API ENEL Token autenticador indisponivel (erro 401) | 🔴 | Chubb - Links de API | Seguir o video de atualizacao manual do token (anexado ao procedimento original) para o passo a passo | NOC | ⏱️ — |
| API ENEL indisponivel (endpoint especifico) | 🟠 | Chubb - Links de API | Analisar o alerta e notificar os contatos da Chubb via e-mail | NOC · e-mail para contatos Chubb | ⏱️ — |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Rede / Conectividade</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| API ENEL Token autenticador indisponivel (erro 401) | Item `autorization.enel.item`, host 'Chubb - Links de API'. Erros 401 nas APIs ENEL estao associados a necessidade de renovar o token de autorizacao, que expira a cada 1 hora pela complexidade da implementacao — NAO e, em si, uma indisponibilidade da API. | Token de autorizacao expirado (renovacao necessaria a cada 1h). | Priorizar a atualizacao do token ANTES de tratar como incidente · Acessar o link do Zabbix do host Chubb (filtro latest.view, hostids=10705) · Selecionar o host, clicar em atualizar, recarregar a pagina e verificar a ultima checagem · Atualizar cada estado individualmente |
| API ENEL indisponivel (endpoint especifico) | Item `services.<endpoint>.<regiao>.[Bearer]`, host 'Chubb - Links de API'. Endpoints monitorados: adesao/subscription (CE), faturamento/invoice (SP), customer-address (CE), request-history (RJ). | Indisponibilidade do lado ENEL (externa) ou falha de token/autenticacao (ver ficha propria de token). | Primeiro descartar o caso do token vencido (ver ficha 'API ENEL Token autenticador indisponivel') · Validar a indisponibilidade diretamente, se possivel |

</details>

##### 🔴 API ENEL Token autenticador indisponivel (erro 401)

Distinguir falha real de token de autenticacao vencido antes de abrir incidente.

**Sintomas:**
* 'API ENEL Token autenticador Indisponivel'
* Erros 401 nas chamadas as APIs ENEL

**Verificações antes de agir:**
* Priorizar a atualizacao do token ANTES de tratar como incidente
* Acessar o link do Zabbix do host Chubb (filtro latest.view, hostids=10705)
* Selecionar o host, clicar em atualizar, recarregar a pagina e verificar a ultima checagem
* Atualizar cada estado individualmente

**Ações:**
* Seguir o video de atualizacao manual do token (anexado ao procedimento original) para o passo a passo
* Somente apos seguir esse procedimento e os alertas permanecerem, considerar o incidente confirmado

**Riscos e ressalvas:**
* Se os alertas normalizarem apos a atualizacao do token, tratava-se de limitacao da ENEL, NAO de incidente -- nao abrir chamado para esse caso

**Critério de resolução:** Alertas normalizam apos a atualizacao do token. Se persistirem apos o procedimento, aí sim e incidente confirmado e deve seguir para o fluxo padrao de 'API ENEL Indisponivel'.

**Observações:** Manual 'Control-M SaaS Chubb' colado pelo usuario em 2026-09-06. Video de referencia citado na fonte original ('atualizacao-manual-token-enel.mp4', anexado pela Vanessa no chamado) -- verificar se o link continua acessivel antes de divulgar.

##### 🟠 API ENEL indisponivel (endpoint especifico)

Validar indisponibilidade real de um endpoint ENEL e notificar os contatos da Chubb.

**Cobre 8 alertas:**
* `ENEL API Adesão(Subscription) CE Indisponível`
* `ENEL API Adesão(Subscription) CE Indisponível a Mais de 2hs`
* `ENEL API Customer-address CE Indisponível`
* `ENEL API Customer-address CE Indisponível a Mais de 2hs`
* `ENEL API Faturamento(Invoice) SP Indisponível`
* `ENEL API Faturamento(Invoice) SP Indisponível a Mais de 2hs`
* `ENEL API Request-history Indisponível`
* `Todas as APIs sem dados`

**Sintomas:**
* 'ENEL API Adesao(Subscription) CE Indisponivel' (+ variante 'a Mais de 2hs')
* 'ENEL API Faturamento(Invoice) SP Indisponivel' (+ variante 'a Mais de 2hs')
* 'ENEL API Customer-address CE Indisponivel' (+ variante 'a Mais de 2hs')
* 'ENEL API Request-history Indisponivel'
* 'Todas as APIs sem dados'

**Verificações antes de agir:**
* Primeiro descartar o caso do token vencido (ver ficha 'API ENEL Token autenticador indisponivel')
* Validar a indisponibilidade diretamente, se possivel

**Ações:**
* Analisar o alerta e notificar os contatos da Chubb via e-mail

**Riscos e ressalvas:**
* 'a Mais de 2hs' e uma segunda severidade do MESMO endpoint (o par avisar/agir do Zabbix) -- nao tratar como incidente novo, e o mesmo caso escalado por tempo

**Critério de resolução:** Endpoint volta a responder normalmente.

**Observações:** Manual 'Control-M SaaS Chubb' colado pelo usuario em 2026-09-06. Contatos em docs/escalation_matrix.md, secao Chubb.

#### Jobs e agendamentos

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Control-M [IN01] — falha de job/agente e roteamento VibeCloud (Oracle x BMC) | 🟠 | Control-M server [IN01] | Arvore de decisao para job Database Oracle (VibeCloud): | Suporte Oracle (procedure iniciou e falhou) ou Suporte BMC (falha do Control-M/integracao) · DeskManager | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Jobs e agendamentos</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Control-M [IN01] — falha de job/agente e roteamento VibeCloud (Oracle x BMC) | 157 alertas, 66 instancias (nomes de job/agente: ABRIR_CHAMADO, ACK, BuscarAlertas, CLAIM, COLETA_FEEDZ, DECIDIR, Disparo3-4, Disparo52, ENDO-FW, ENVIAR, ENVIA_MSG_TEAMS, EnviaMsgZap3-4 e outros). Severidade concentrada em Warning (142), com 5 Disaster e 3 High -- os casos graves tendem a ser 'Server disconnected'/'Server is down', nao falha pontual de um job. Todo job do tipo 'Database Oracle' e relacionado ao VibeCloud. | Perda de comunicacao entre o Control-M e o servidor monitorado, ou falha real na execucao do job/agente nomeado. Para jobs do tipo Database Oracle, a causa se separa em duas: falha da propria procedure (ex.: erro do FLASH) ou falha do Control-M/integracao com o Oracle. | Verificar no console do Control-M se o servidor/agente aparece conectado · Se for job do tipo Database Oracle: abrir o OUTPUT do job e checar se a procedure chegou a iniciar · Confirmar se e um evento isolado ou se varios jobs do mesmo agente falharam junto (sintoma de queda do agente, nao dos jobs) |

</details>

##### 🟠 Control-M [IN01] — falha de job/agente e roteamento VibeCloud (Oracle x BMC)

Tratar falhas do orquestrador Control-M e decidir corretamente entre a fila Suporte Oracle e a fila Suporte BMC.

**Sintomas:**
* 'Control-M: Server disconnected' / 'Server error' / 'Server is down'
* 'Control-M: Server version has changed'
* 'Control-M: Job [NOME] - SubApplication X - (ODate: N): status [...]' -- ex. real: Job [STP_PROCESSA_PEDIDO]

**Verificações antes de agir:**
* Verificar no console do Control-M se o servidor/agente aparece conectado
* Se for job do tipo Database Oracle: abrir o OUTPUT do job e checar se a procedure chegou a iniciar
* Confirmar se e um evento isolado ou se varios jobs do mesmo agente falharam junto (sintoma de queda do agente, nao dos jobs)

**Ações:**
* Arvore de decisao para job Database Oracle (VibeCloud):
* 1) Procedure INICIOU mas deu erro do FLASH ou de outra plataforma externa -> problema na propria procedure -> abrir chamado na fila Suporte Oracle, anexando as evidencias do output.
* 2) Procedure NAO iniciou / falha de conexao Control-M <-> Oracle -> problema no Control-M ou na integracao -> abrir chamado na fila Suporte BMC.
* Exemplo real: Job [STP_PROCESSA_PEDIDO] falhou com Exit Code 20000 na proc VIBE_LJ.STP_PROCESSA_PEDIDO por HTTP 502/Status 400 do provedor FLASH -- procedure iniciou e falhou externamente -> Suporte Oracle.
* Para RotinaComFalha/CargaComFalha (RH Cloud, fora do Zabbix): se o erro mudar numa reexecucao, nao abrir chamado duplicado -- vincular ao chamado existente ou abrir novo somente se o erro for inedito.
* --- Excecao: job TransfereArquivoChubb (SubApplication ENEL, cliente Chubb) ---
* Regra de Long Run (geral, qualquer job): apos abrir o chamado, acompanhar por ate 10 minutos antes de qualquer tratativa. Se normalizar dentro da janela, o chamado pode ser fechado pelo N1, desde que o motivo da normalizacao seja registrado no ITSM.
* Especifico do step TransfereArquivoChubb_Conciliado em Long Run:
* 1) Verificar no container 'arquivos' do Azure Storage se o arquivo conciliado foi gerado.
* 2) Se o arquivo NAO foi gerado: analisar imediatamente e escalonar se necessario.
* 3) Se o arquivo FOI gerado: parar a execucao do step, reexecutar; se persistir Long Run apos a reexecucao, abrir chamado para analise.
* NUNCA interromper/reexecutar o step sem confirmar que o arquivo ja foi gerado.
* Para os DEMAIS erros deste job (nao Long Run): registrar no ITSM, anexar print do alerta + print do output do job (obrigatorio antes de escalonar), e encaminhar para a fila Suporte-BMC -- exceto severidade Critica, que aciona por telefone imediatamente.

**Riscos e ressalvas:**
* A regra 'applications--job' cobre o MESMO host (Control-M server [IN01]) porque ele pertence a dois host groups (Applications e Control-M/IN01). Esta e a ficha primaria -- nao documentar a mesma coisa duas vezes.
* O time Suporte BMC nao tem acao quando a procedure iniciou e falhou por erro de plataforma externa -- nao escalar para BMC nesse caso.
* O alert_key deste job muda todo dia (o ODate entra na chave: '...odate-260904...' vs '...odate-260905...'). Documentar por override de alert_key ficaria orfao em 24h -- por isso este caso esta na REGRA (agrupa por nome do job, estavel), nao num override.
* TransfereArquivoChubb NAO e job do tipo 'Database Oracle' -- a arvore Suporte Oracle x Suporte BMC descrita acima NAO se aplica a ele. Confirmar visualmente o nome/tipo do job antes de aplicar a arvore de decisao Oracle x BMC.

**Critério de resolução:** Job volta a executar com sucesso (Ended OK) na proxima janela, ou o servidor/agente Control-M volta a aparecer conectado.

**Observações:** Horario de atendimento do Suporte BMC/Oracle: A CONFIRMAR com os times (nao veio definido na fonte original). Ver docs/escalation_matrix.md. Manual 'Control-M SaaS Chubb' colado pelo usuario em 2026-09-06. Contato critico Control-M: Bruno Rezegue Mendes (91) 98298-4301; Marcos Paulo Pinheiro Correa tambem consta como contato critico, mas SEM TELEFONE registrado na fonte -- confirmar. Duvida em aberto: o texto geral diz que N1/NOC pode reexecutar jobs 'quando permitido', mas a secao especifica de Control-M atribui reexecucao (ate 3x) ao N2 (Bruno Mendes) -- confirmar quem executa de fato antes de agir.

**Evidências obrigatórias no chamado:** Output completo do job · ODate · Codigo/nome do pedido ou processo afetado · Print do alerta · Print do output do job (obrigatorios antes de qualquer escalonamento deste job)

### Master Support (interno)

**6 alerta(s)** em 6 procedimento(s) · 1 host(s): `ONESecure`

> Nossa própria infraestrutura: ONESecure, Desk Manager, n8n.
{.is-info}

#### ☎️ Acionamento

| Fila / Time | Canal | Escalonamento | Alertas cobertos |
| :--- | :--- | :--- | ---: |
| **SOC** | DeskManager -> fila SOC | analista SOC · analista SOC (somente horario comercial) | 2 |
| **Sobreaviso MSMonitor** | Telefone | Jordy — (91) 99165-4121 | 2 |
| **Suporte DEV** | DeskManager | — | 2 |

#### Segurança e integridade

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| ONESecure — API indisponivel | 🟠 | ONESecure | Validar no link de status. Se persistir por mais de 5 min, abrir chamado com evidencias e horarios. Se for recorrente, pedir ajuste de trigger. | SOC · DeskManager -> fila SOC | ⏱️ 5 min |
| SOC / ONESecure — Triagem N1 de incidentes (Alto/Critico) | 🟠 | ONESecure | Coletar as 5 evidencias obrigatorias: data/hora (Timestamp/timestamp), severidade (Classificacao do evento ou rule.level), nome/descricao do alerta (Regra/rule.description), host/agente afetado (Agente/agent.name), log/output (JSON ou log do registro). | SOC · DeskManager -> fila SOC | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Segurança e integridade</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| ONESecure — API indisponivel | API do ONESecure fora do ar (http://200.219.199.10:9009/health). | Falha na plataforma ONESecure ou na rede ate ela. | Validar no link de status do SOC |
| SOC / ONESecure — Triagem N1 de incidentes (Alto/Critico) | 29 alertas no host 'ONESecure' (grupo Master Support), 27 instancias (numeros de incidente/ticket: INC-AGP-..., INC00000...). Severidades: 18 Disaster, 5 High, 4 Average, 2 Warning. O N1 atua SOMENTE em incidentes Alto ou Critico -- classificacao por 'rule.level': 0-6 Baixo (fora do escopo), 7-11 Medio (fora do escopo), 12-14 Alto (triagem), 15+ Critico (triagem). | Evento de seguranca real detectado pela plataforma (MITRE ATT&CK / monitoramento de logs) classificado como Alto ou Critico. | Home -> Visao tecnica -> Incidentes: existe registro Alto ou Critico? Se nao, encerrar o fluxo. · Se sim: Detectar -> Dashboard MITRE ATT&CK, filtros Severidade=Alta/Critica e periodo=ultima 1 hora, localizar o evento. · Evento nao localizado no dashboard: Detectar -> Monitoramento de logs, filtrar por rule.level, periodo=ultimos 30 minutos. |

</details>

##### 🟠 ONESecure — API indisponivel

**Sintomas:**
* 'ONESecure: API indisponivel' — checar o link de status

**Verificações antes de agir:**
* Validar no link de status do SOC

**Ações:**
* Validar no link de status. Se persistir por mais de 5 min, abrir chamado com evidencias e horarios. Se for recorrente, pedir ajuste de trigger.

**Critério de resolução:** Link de status volta a responder normalmente.

**Observações:** Severidade: Alta. SLA: 5 min. Pagina de status: https://wiki-noc.prod.cloud.dnxbrasil.com.br/pt-br/vibe/Seguranca/SOC/Procedimentos/status. Ver docs/escalation_matrix.md para a matriz completa de filas, contatos e horarios. Fluxo geral: validar severidade -> respeitar tolerancia (se media/baixa) -> coletar evidencias (host, data/hora, print/output) -> abrir chamado no DeskManager -> transferir para a fila -> se nao houver retorno dentro do SLA, escalar por Teams/telefone do sobreaviso.

##### 🟠 SOC / ONESecure — Triagem N1 de incidentes (Alto/Critico)

Identificar incidentes classificados como Alto ou Critico no ONESecure, coletar as evidencias minimas e encaminhar para a fila do SOC dentro do SLA -- sem investigar ou responder ao incidente (isso e do SOC).

**Sintomas:**
* 'ONESecure: Ticket aberto [xxxxxx]'
* 'ONESecure: Incidente em Preparacao [INC-AGP-...]: <descricao>'
* 'ONESecure: API indisponivel (http://200.219.199.10:9009/health)' -- ver ficha propria dessa API
* 'ONESecure: Falha na coleta de tickets'

**Verificações antes de agir:**
* Home -> Visao tecnica -> Incidentes: existe registro Alto ou Critico? Se nao, encerrar o fluxo.
* Se sim: Detectar -> Dashboard MITRE ATT&CK, filtros Severidade=Alta/Critica e periodo=ultima 1 hora, localizar o evento.
* Evento nao localizado no dashboard: Detectar -> Monitoramento de logs, filtrar por rule.level, periodo=ultimos 30 minutos.

**Ações:**
* Coletar as 5 evidencias obrigatorias: data/hora (Timestamp/timestamp), severidade (Classificacao do evento ou rule.level), nome/descricao do alerta (Regra/rule.description), host/agente afetado (Agente/agent.name), log/output (JSON ou log do registro).
* Abrir chamado no modelo padrao: '[ONESecure][ALTO/CRITICO] <Nome do alerta>' com data/hora, severidade, alerta, host/agente, log/output e origem da evidencia (Dashboard MITRE ATT&CK ou Monitoramento de logs).
* Encaminhar o chamado para a fila do SOC.
* Em horario comercial: comunicar o analista do SOC pelo Teams com o ID do chamado. Fora do horario comercial: NAO acionar diretamente -- o chamado segue na fila do SOC.

**Riscos e ressalvas:**
* N1 nao investiga nem responde ao incidente -- so faz a triagem inicial e encaminha.
* Fora do horario comercial, acionar o analista diretamente e fora do procedimento -- o chamado deve apenas ficar na fila.

**Como validar:** Conferir se as 5 evidencias minimas foram registradas e se o chamado foi corretamente direcionado para a fila do SOC antes de considerar a triagem concluida.

**Critério de resolução:** Chamado aberto, com as 5 evidencias, corretamente encaminhado para a fila do SOC.

**Observações:** Pagina de status do SOC: https://wiki-noc.prod.cloud.dnxbrasil.com.br/pt-br/vibe/Seguranca/SOC/Procedimentos/status. A ficha da familia 'ONESecure: API indisponivel' (SLA 5 min) e separada desta triagem N1 -- ver rule|onesecure-api-indisponivel-http-200-219-199-10-9009-health.

**Evidências obrigatórias no chamado:** Data/hora · Severidade (rule.level) · Nome/descricao do alerta · Host/agente afetado · Log/output (JSON)

#### Fora do Zabbix

> Estes alertas **não vêm do Zabbix**: quem avisa é o próprio sistema de origem, por e-mail ou webhook. Não espere encontrá-los no painel.
{.is-warning}

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Grafana Integration — Connection prematurely closed BEFORE response | ⚪ | fora do Zabbix | Aguardar o tempo limite. Se nao normalizar, abrir chamado. | Suporte DEV · DeskManager | ⏱️ Imediato |
| MSMonitor — Erro na sincronizacao de integracao | ⚪ | fora do Zabbix | Aguardar a mensagem de 'normalizada'. Se persistir, ligar para o plantao. | Sobreaviso MSMonitor · Telefone | ⏱️ — |
| MSMonitor — STALL | ⚪ | fora do Zabbix | Aguardar a recuperacao automatica. Se persistir, acionar o plantao. | Sobreaviso MSMonitor · Telefone | ⏱️ — |
| Zabbix Integration — Falha na conexao ao executar operacao | ⚪ | fora do Zabbix | Aguardar o tempo limite. Se nao normalizar, abrir chamado. | Suporte DEV · DeskManager | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Fora do Zabbix</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Grafana Integration — Connection prematurely closed BEFORE response | Conexao encerrada com a API do Grafana antes da resposta. | Instabilidade de rede/API. | — |
| MSMonitor — Erro na sincronizacao de integracao | Erro ao carregar alertas de uma integracao (ex.: 'zabb', id 12). | Falha no getAlerts com o Zabbix. | Verificar se ja chegou a notificacao 'Integracao normalizada' antes de acionar o sobreaviso |
| MSMonitor — STALL | Nenhum arquivo de alerta recebido em N verificacoes (coletor parado). | Coletor parado (ex.: cliente Votorantim). | Verificar se ja chegou a notificacao 'Integracao normalizada' antes de acionar o sobreaviso |
| Zabbix Integration — Falha na conexao ao executar operacao | MSMonitor falhando ao se conectar na API do Zabbix. | Instabilidade de rede/API. | — |

</details>

##### ⚪ Grafana Integration — Connection prematurely closed BEFORE response

**Sintomas:**
* Notificacao 'Connection prematurely closed BEFORE response' (Grafana Integration)

**Ações:**
* Aguardar o tempo limite. Se nao normalizar, abrir chamado.

**Critério de resolução:** Integracao com o Grafana volta a responder normalmente.

**Observações:** Severidade: Alta. SLA: 7 min (5m + 2m). Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ MSMonitor — Erro na sincronizacao de integracao

**Sintomas:**
* Notificacao 'Erro na sincronizacao de integracao' do MSMonitor

**Verificações antes de agir:**
* Verificar se ja chegou a notificacao 'Integracao normalizada' antes de acionar o sobreaviso

**Ações:**
* Aguardar a mensagem de 'normalizada'. Se persistir, ligar para o plantao.

**Critério de resolução:** Notificacao 'Integracao normalizada' recebida.

**Observações:** Severidade: Alta. SLA: Imediato (apos validacao). Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ MSMonitor — STALL

**Sintomas:**
* Notificacao 'STALL' do MSMonitor

**Verificações antes de agir:**
* Verificar se ja chegou a notificacao 'Integracao normalizada' antes de acionar o sobreaviso

**Ações:**
* Aguardar a recuperacao automatica. Se persistir, acionar o plantao.

**Critério de resolução:** Coletor volta a enviar arquivos de alerta normalmente.

**Observações:** Severidade: Alta. SLA: Imediato (apos validacao). Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

##### ⚪ Zabbix Integration — Falha na conexao ao executar operacao

**Sintomas:**
* Notificacao 'Falha na conexao ao executar operacao' (Zabbix Integration)

**Ações:**
* Aguardar o tempo limite. Se nao normalizar, abrir chamado.

**Critério de resolução:** Integracao com o Zabbix volta a responder normalmente.

**Observações:** Severidade: Alta. SLA: 7 min (5m + 2m). Fluxo geral: validar -> coletar evidencias -> abrir chamado -> transferir para a fila -> escalar se faltar retorno no SLA. Ver docs/escalation_matrix.md.

### Votorantim

**6 alerta(s)** em 6 procedimento(s) · 2 host(s): `Control-M DEV Votorantim`, `Control-M PRD Votorantim`

> O host PRD tem ~16 mil alertas de job e está excluído do escopo do NOC em scopes.json — o cliente é monitorado, aquele host específico não é analisado no plantão.
{.is-info}

#### ☎️ Acionamento

| Fila / Time | Canal | Escalonamento | Alertas cobertos |
| :--- | :--- | :--- | ---: |
| **NOC (N1) → N2 Control-M da Master** | ServiceNow (Votorantim) · ServiceNow (Votorantim) — retido no NOC até orientação do N2 | N2 de plantão (Roberto Lima (91) 98431-8588 / Jordy Oliveira (91) 99165-4121) → N3 (Marcos Correa (91) 98455-1564 / Rafael Silva +1 (321) 946-4112) → liderança. Fornecedores: Tivit (Ivan Vargem (11) 98911-0379) e NTT (0800 200 3282 / servicedesk.br@global.ntt) · N2 de plantão (Roberto Lima / Jordy Oliveira) → N3 (Marcos Correa / Rafael Silva) | 6 |

#### Jobs e agendamentos

<div style="width: 100%; overflow-x: auto;">

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| Agente Control-M desabilitado (disabled) — Votorantim | 🟠 | Control-M PRD Votorantim | FASE 1 — Abrir o INC no ServiceNow IMEDIATAMENTE, antes da análise técnica: garante o registro exato do início da falha | NOC (N1) → N2 Control-M da Master · ServiceNow (Votorantim) — retido no NOC até orientação do N2 | ⏱️ 5 min |
| Agente Control-M indisponível (Unavailable) — Votorantim | 🟠 | Control-M PRD Votorantim | FASE 1 — Abrir o INC no ServiceNow IMEDIATAMENTE, antes da análise técnica: garante o registro exato do início da falha | NOC (N1) → N2 Control-M da Master · ServiceNow (Votorantim) — retido no NOC até orientação do N2 | ⏱️ 5 min |
| Control-M Server com erro — Votorantim (DEV) | 🔵 | Control-M DEV Votorantim | Abrir INC no ServiceNow e manter retido no NOC | NOC (N1) → N2 Control-M da Master · ServiceNow (Votorantim) | ⏱️ Imediato |
| Control-M Server desconectado — Votorantim (DEV) | 🔵 | Control-M DEV Votorantim | Abrir INC no ServiceNow e manter retido no NOC | NOC (N1) → N2 Control-M da Master · ServiceNow (Votorantim) | ⏱️ Imediato |
| Control-M Server fora do ar — Votorantim (DEV) | 🔵 | Control-M DEV Votorantim | Abrir INC no ServiceNow e manter retido no NOC | NOC (N1) → N2 Control-M da Master · ServiceNow (Votorantim) | ⏱️ Imediato |
| Control-M Server mudou de versão — Votorantim (DEV) | 🔵 | Control-M DEV Votorantim | Abrir INC no ServiceNow e manter retido no NOC | NOC (N1) → N2 Control-M da Master · ServiceNow (Votorantim) | ⏱️ Imediato |

</div>

<details>
<summary>🔍 <strong>Referência técnica — Jobs e agendamentos</strong></summary>

| Alerta | O que significa | Causa provável | Verificações antes de agir |
| :--- | :--- | :--- | :--- |
| Agente Control-M desabilitado (disabled) — Votorantim | Item de LLD 'Agent discovery' no host 'Control-M PRD Votorantim' — 30 agentes descobertos. O agente está desabilitado no Control-M/Server: pode ser desativação manual (manutenção) ou automática após falhas sucessivas. | Queda do serviço do agente, servidor offline, bloqueio de rede, ou desativação no Control-M/Server. | FASE 2 — Consultar a matriz de agentes (em observações) para saber se é Host Group (10 min) ou Isolado (5 min). O cronômetro já está correndo · FASE 2 — No Control-M > Monitoring, filtrar `Host` Like/= <nome do agente> e levantar o impacto na malha · Contar SÓ o que é impacto direto: Unknown/Executing (o Control-M perdeu o status real da execução — pode ter abortado ou estar rodando solto), Wait Host (retidos) e Ended Not OK (falharam com a queda) · IGNORAR: Ended OK (concluíram antes da queda) e Wait for Event / Wait Resource / Wait Workload / Wait User (aguardam condição lógica, não rodariam mesmo com o agente no ar) · Capturar os prints da análise — servem para o chamado e para o e-mail |
| Agente Control-M indisponível (Unavailable) — Votorantim | Item de LLD 'Agent discovery' no host 'Control-M PRD Votorantim' — 30 agentes descobertos. O Control-M/Server perdeu comunicação com o agente: todos os jobs daquele host param de ser submetidos, com efeito cascata na malha (Late Submission e travamento das cadeias dependentes). | Queda do serviço do agente, servidor offline, bloqueio de rede, ou desativação no Control-M/Server. | FASE 2 — Consultar a matriz de agentes (em observações) para saber se é Host Group (10 min) ou Isolado (5 min). O cronômetro já está correndo · FASE 2 — No Control-M > Monitoring, filtrar `Host` Like/= <nome do agente> e levantar o impacto na malha · Contar SÓ o que é impacto direto: Unknown/Executing (o Control-M perdeu o status real da execução — pode ter abortado ou estar rodando solto), Wait Host (retidos) e Ended Not OK (falharam com a queda) · IGNORAR: Ended OK (concluíram antes da queda) e Wait for Event / Wait Resource / Wait Workload / Wait User (aguardam condição lógica, não rodariam mesmo com o agente no ar) · Capturar os prints da análise — servem para o chamado e para o e-mail |
| Control-M Server com erro — Votorantim (DEV) | O servidor Control-M do ambiente DEV reportou erro. | Queda, erro ou reinício do Control-M/Server, ou atualização de versão. | Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs · Verificar se houve janela de manutenção comunicada |
| Control-M Server desconectado — Votorantim (DEV) | O servidor Control-M do ambiente DEV perdeu conexão. | Queda, erro ou reinício do Control-M/Server, ou atualização de versão. | Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs · Verificar se houve janela de manutenção comunicada |
| Control-M Server fora do ar — Votorantim (DEV) | O servidor Control-M do ambiente DEV não está respondendo. | Queda, erro ou reinício do Control-M/Server, ou atualização de versão. | Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs · Verificar se houve janela de manutenção comunicada |
| Control-M Server mudou de versão — Votorantim (DEV) | A versão do servidor Control-M do ambiente DEV mudou — normalmente atualização planejada, mas mudança não comunicada merece confirmação. | Queda, erro ou reinício do Control-M/Server, ou atualização de versão. | Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs · Verificar se houve janela de manutenção comunicada |

</details>

##### 🟠 Agente Control-M desabilitado (disabled) — Votorantim

Restabelecer a submissão de jobs do host afetado e medir o impacto na malha antes de acionar o N2 — sem acionar por intermitência que se resolve sozinha.

**Sintomas:**
* 'Control-M: Agent [<nome>]: status [Unavailable (1)]' — o Control-M/Server não consegue comunicar com o agente (serviço caído, servidor offline ou bloqueio de rede)
* 'Control-M: Agent [<nome>]: status disabled' — agente desabilitado no Control-M/Server (manutenção manual ou desativação automática após falhas sucessivas)

**Verificações antes de agir:**
* FASE 2 — Consultar a matriz de agentes (em observações) para saber se é Host Group (10 min) ou Isolado (5 min). O cronômetro já está correndo
* FASE 2 — No Control-M > Monitoring, filtrar `Host` Like/= <nome do agente> e levantar o impacto na malha
* Contar SÓ o que é impacto direto: Unknown/Executing (o Control-M perdeu o status real da execução — pode ter abortado ou estar rodando solto), Wait Host (retidos) e Ended Not OK (falharam com a queda)
* IGNORAR: Ended OK (concluíram antes da queda) e Wait for Event / Wait Resource / Wait Workload / Wait User (aguardam condição lógica, não rodariam mesmo com o agente no ar)
* Capturar os prints da análise — servem para o chamado e para o e-mail

**Ações:**
* FASE 1 — Abrir o INC no ServiceNow IMEDIATAMENTE, antes da análise técnica: garante o registro exato do início da falha
* FASE 3 — Esgotado o tempo de tolerância, verificar no MsMonitor se o alerta normalizou:
* NORMALIZOU: atualizar o INC com a análise de impacto (mesmo que seja 'nenhum job afetado') e ENCERRAR o chamado. Enviar e-mail informativo para noc-controlm@vibetecnologia.com e esp-controlm@vibetecnologia.com (Template 4).
* PERSISTIU: atualizar o INC com a análise e os prints, enviar e-mail de incidente para os mesmos endereços (Template 5) e acionar o N2 de plantão — primeiro por Teams, sem retorno por ligação. Consultar a escala oficial ESCALA_NOC_2026.xlsx.
* FASE 4 — Aguardar o retorno do N2: se ele normalizar ou identificar falso positivo, encerrar o chamado com o aval registrado; se confirmar falha de infraestrutura, o N1 transfere para a fila do fornecedor e faz o acionamento conforme orientação dele.

**Riscos e ressalvas:**
* Parece intencional e não é presumido como tal: `disabled` exige a MESMA tratativa do `Unavailable` até que o N2 ou o fornecedor confirmem manutenção programada.
* `disabled` NÃO é presumido como manutenção programada: tratar como incidente até que o N2 ou o fornecedor confirmem formalmente. Nunca presumir que foi de propósito.
* Job travado em Executing/Unknown é o caso mais delicado: o painel mostra amarelo, mas a execução real pode já ter falhado ou concluído no servidor de origem.
* Se o N2 de plantão não atender: acionar o outro analista de N2, depois o N3 (Marcos Paulo Correa / Rafael Ferreira da Silva) e, em último caso, a liderança da Master. Registrar no chamado TODAS as tentativas, com horário de cada uma.

**Como validar:** Agente volta a aparecer disponível no Control-M e os jobs que estavam em Wait Host voltam a ser submetidos.

**Critério de resolução:** Agente volta a comunicar com o Control-M/Server e a malha volta a submeter os jobs do host. Se normalizou dentro da tolerância, o INC é encerrado pelo próprio N1.

**Observações:** Manual 'NOC Votorantim — Control-M' colado pelo time em 2026-09-06. Operação 24x7. TOLERÂNCIA ANTES DE ACIONAR O N2 — Host Group (10 min de tolerância): brsaowvapp24vc/25vc/26vc (Tivit, DataFactory) · brsaowvqlk06vc/07vc/08vc (Tivit, Qliksense) · vidb0302/0303/0304 (Tivit, SAP BW) · awslcctrlmagt01 a 07 (NTT, SAP S/4) · awslcctrlmprd02 (NTT, Produção). ISOLADO (5 min de tolerância): brsaowvcgn02vc (Tivit, Cognos) · brsaowsfs01vc (Tivit, Transf. Arquivos) · brccqwsfs01vc (Tivit, SFTP ONS) · awslcctrlmprd04 (NTT, Produção). Os agentes vide0502ctm a vide0508ctm constam como permanentemente desabilitados e não devem gerar chamado. Acesso ao Control-M: VPN FortiClient da Fábrica, com ZTNA/Netskope como contingência (procedimento completo na wiki do NOC). Chamados no ServiceNow da Votorantim, obrigatoriamente como Incidente (INC), nunca Requisição.

**Evidências obrigatórias no chamado:** Print do filtro de impacto no Monitoring (Host = agente) · Nome do agente e sua arquitetura (Isolado ou Host Group) · Horário de início da ocorrência · Fornecedor responsável (Tivit ou NTT)

##### 🟠 Agente Control-M indisponível (Unavailable) — Votorantim

Restabelecer a submissão de jobs do host afetado e medir o impacto na malha antes de acionar o N2 — sem acionar por intermitência que se resolve sozinha.

**Sintomas:**
* 'Control-M: Agent [<nome>]: status [Unavailable (1)]' — o Control-M/Server não consegue comunicar com o agente (serviço caído, servidor offline ou bloqueio de rede)
* 'Control-M: Agent [<nome>]: status disabled' — agente desabilitado no Control-M/Server (manutenção manual ou desativação automática após falhas sucessivas)

**Verificações antes de agir:**
* FASE 2 — Consultar a matriz de agentes (em observações) para saber se é Host Group (10 min) ou Isolado (5 min). O cronômetro já está correndo
* FASE 2 — No Control-M > Monitoring, filtrar `Host` Like/= <nome do agente> e levantar o impacto na malha
* Contar SÓ o que é impacto direto: Unknown/Executing (o Control-M perdeu o status real da execução — pode ter abortado ou estar rodando solto), Wait Host (retidos) e Ended Not OK (falharam com a queda)
* IGNORAR: Ended OK (concluíram antes da queda) e Wait for Event / Wait Resource / Wait Workload / Wait User (aguardam condição lógica, não rodariam mesmo com o agente no ar)
* Capturar os prints da análise — servem para o chamado e para o e-mail

**Ações:**
* FASE 1 — Abrir o INC no ServiceNow IMEDIATAMENTE, antes da análise técnica: garante o registro exato do início da falha
* FASE 3 — Esgotado o tempo de tolerância, verificar no MsMonitor se o alerta normalizou:
* NORMALIZOU: atualizar o INC com a análise de impacto (mesmo que seja 'nenhum job afetado') e ENCERRAR o chamado. Enviar e-mail informativo para noc-controlm@vibetecnologia.com e esp-controlm@vibetecnologia.com (Template 4).
* PERSISTIU: atualizar o INC com a análise e os prints, enviar e-mail de incidente para os mesmos endereços (Template 5) e acionar o N2 de plantão — primeiro por Teams, sem retorno por ligação. Consultar a escala oficial ESCALA_NOC_2026.xlsx.
* FASE 4 — Aguardar o retorno do N2: se ele normalizar ou identificar falso positivo, encerrar o chamado com o aval registrado; se confirmar falha de infraestrutura, o N1 transfere para a fila do fornecedor e faz o acionamento conforme orientação dele.

**Riscos e ressalvas:**
* `disabled` NÃO é presumido como manutenção programada: tratar como incidente até que o N2 ou o fornecedor confirmem formalmente. Nunca presumir que foi de propósito.
* Job travado em Executing/Unknown é o caso mais delicado: o painel mostra amarelo, mas a execução real pode já ter falhado ou concluído no servidor de origem.
* Se o N2 de plantão não atender: acionar o outro analista de N2, depois o N3 (Marcos Paulo Correa / Rafael Ferreira da Silva) e, em último caso, a liderança da Master. Registrar no chamado TODAS as tentativas, com horário de cada uma.

**Como validar:** Agente volta a aparecer disponível no Control-M e os jobs que estavam em Wait Host voltam a ser submetidos.

**Critério de resolução:** Agente volta a comunicar com o Control-M/Server e a malha volta a submeter os jobs do host. Se normalizou dentro da tolerância, o INC é encerrado pelo próprio N1.

**Observações:** Manual 'NOC Votorantim — Control-M' colado pelo time em 2026-09-06. Operação 24x7. TOLERÂNCIA ANTES DE ACIONAR O N2 — Host Group (10 min de tolerância): brsaowvapp24vc/25vc/26vc (Tivit, DataFactory) · brsaowvqlk06vc/07vc/08vc (Tivit, Qliksense) · vidb0302/0303/0304 (Tivit, SAP BW) · awslcctrlmagt01 a 07 (NTT, SAP S/4) · awslcctrlmprd02 (NTT, Produção). ISOLADO (5 min de tolerância): brsaowvcgn02vc (Tivit, Cognos) · brsaowsfs01vc (Tivit, Transf. Arquivos) · brccqwsfs01vc (Tivit, SFTP ONS) · awslcctrlmprd04 (NTT, Produção). Os agentes vide0502ctm a vide0508ctm constam como permanentemente desabilitados e não devem gerar chamado. Acesso ao Control-M: VPN FortiClient da Fábrica, com ZTNA/Netskope como contingência (procedimento completo na wiki do NOC). Chamados no ServiceNow da Votorantim, obrigatoriamente como Incidente (INC), nunca Requisição.

**Evidências obrigatórias no chamado:** Print do filtro de impacto no Monitoring (Host = agente) · Nome do agente e sua arquitetura (Isolado ou Host Group) · Horário de início da ocorrência · Fornecedor responsável (Tivit ou NTT)

##### 🔵 Control-M Server com erro — Votorantim (DEV)

Reagir a falha do próprio servidor Control-M, que afeta a malha inteira.

**Sintomas:**
* 'Control-M: Server error'

**Verificações antes de agir:**
* Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs
* Verificar se houve janela de manutenção comunicada

**Ações:**
* Abrir INC no ServiceNow e manter retido no NOC
* Acionar o N2 de plantão (Teams, depois ligação) — falha do servidor afeta toda a malha, não um host isolado

**Riscos e ressalvas:**
* Diferente do agente (que afeta um host), falha do SERVIDOR afeta a malha inteira: não aplicar a tolerância de 5/10 minutos da matriz de agentes.

**Critério de resolução:** Servidor Control-M volta a operar e a malha volta a submeter jobs.

**Observações:** Manual 'NOC Votorantim — Control-M' colado pelo time em 2026-09-06. Host 'Control-M DEV Votorantim'. Severidade Information no Zabbix subestima o caso — confirmar com o time se o ambiente DEV justifica o mesmo tratamento do PRD.

##### 🔵 Control-M Server desconectado — Votorantim (DEV)

Reagir a falha do próprio servidor Control-M, que afeta a malha inteira.

**Sintomas:**
* 'Control-M: Server disconnected'

**Verificações antes de agir:**
* Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs
* Verificar se houve janela de manutenção comunicada

**Ações:**
* Abrir INC no ServiceNow e manter retido no NOC
* Acionar o N2 de plantão (Teams, depois ligação) — falha do servidor afeta toda a malha, não um host isolado

**Riscos e ressalvas:**
* Diferente do agente (que afeta um host), falha do SERVIDOR afeta a malha inteira: não aplicar a tolerância de 5/10 minutos da matriz de agentes.

**Critério de resolução:** Servidor Control-M volta a operar e a malha volta a submeter jobs.

**Observações:** Manual 'NOC Votorantim — Control-M' colado pelo time em 2026-09-06. Host 'Control-M DEV Votorantim'. Severidade Information no Zabbix subestima o caso — confirmar com o time se o ambiente DEV justifica o mesmo tratamento do PRD.

##### 🔵 Control-M Server fora do ar — Votorantim (DEV)

Reagir a falha do próprio servidor Control-M, que afeta a malha inteira.

**Sintomas:**
* 'Control-M: Server is down'

**Verificações antes de agir:**
* Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs
* Verificar se houve janela de manutenção comunicada

**Ações:**
* Abrir INC no ServiceNow e manter retido no NOC
* Acionar o N2 de plantão (Teams, depois ligação) — falha do servidor afeta toda a malha, não um host isolado

**Riscos e ressalvas:**
* Diferente do agente (que afeta um host), falha do SERVIDOR afeta a malha inteira: não aplicar a tolerância de 5/10 minutos da matriz de agentes.

**Critério de resolução:** Servidor Control-M volta a operar e a malha volta a submeter jobs.

**Observações:** Manual 'NOC Votorantim — Control-M' colado pelo time em 2026-09-06. Host 'Control-M DEV Votorantim'. Severidade Information no Zabbix subestima o caso — confirmar com o time se o ambiente DEV justifica o mesmo tratamento do PRD.

##### 🔵 Control-M Server mudou de versão — Votorantim (DEV)

Reagir a falha do próprio servidor Control-M, que afeta a malha inteira.

**Sintomas:**
* 'Control-M: Server version has changed'

**Verificações antes de agir:**
* Confirmar no Control-M se o servidor responde e se a malha continua submetendo jobs
* Verificar se houve janela de manutenção comunicada

**Ações:**
* Abrir INC no ServiceNow e manter retido no NOC
* Acionar o N2 de plantão (Teams, depois ligação) — falha do servidor afeta toda a malha, não um host isolado

**Riscos e ressalvas:**
* Diferente do agente (que afeta um host), falha do SERVIDOR afeta a malha inteira: não aplicar a tolerância de 5/10 minutos da matriz de agentes.

**Critério de resolução:** Servidor Control-M volta a operar e a malha volta a submeter jobs.

**Observações:** Manual 'NOC Votorantim — Control-M' colado pelo time em 2026-09-06. Host 'Control-M DEV Votorantim'. Severidade Information no Zabbix subestima o caso — confirmar com o time se o ambiente DEV justifica o mesmo tratamento do PRD.

---

Gerado em 2026-09-06T20:27:52Z · 41 procedimento(s) validado(s) cobrindo 48 alerta(s) em 4 cliente(s) · fonte: `docs/alerts/` do Zabbix-Wiki.

Fora desta página, por serem atendidos por outro NOC: Banpará.
