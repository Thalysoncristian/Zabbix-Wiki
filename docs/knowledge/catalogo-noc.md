# 📘 Catálogo de Alertas Internos — Monitoramento Zabbix

> Cópia do wiki do NOC, usada pelo Zabbix-Wiki como fonte de conhecimento já
> validado. Fonte: https://wiki-noc.prod.cloud.dnxbrasil.com.br
>
> Para atualizar: cole aqui a versão nova do wiki e rode `python main.py kb`.
> O formato das tabelas é o mesmo do bloco "Como adicionar novos itens".

## ☎️ Matriz de acionamento

| Fila / Time | Responsável por | Canal primário | Escalonamento | Horário |
| :--- | :--- | :--- | :--- | :--- |
| **Infraestrutura** | Rede, links, APs, VPN, disco, servidores | DeskManager | Teams — Rafael Sales | A confirmar |
| **SOC** | Incidentes de segurança, ONESecure | DeskManager → fila SOC | Teams (analista) | Acionamento direto somente em horário comercial |
| **Suporte Oracle** | Procedures, RH Cloud, cargas e rotinas | DeskManager | — | A confirmar |
| **Suporte BMC** | Control-M e integração Control-M ↔ Oracle | DeskManager | — | A confirmar |
| **Suporte DEV** | Integrações MSMonitor (Grafana / Zabbix API) | DeskManager | — | A confirmar |
| **Sobreaviso MSMonitor** | Coletores e sincronização MSMonitor | Telefone — Jordy (91) 99165-4121 | — | Plantão |
| **RH** | Benefícios, ativação de colaborador | DeskManager | — | A confirmar |
| **Administrativo** | Pagamentos, centro de custo | DeskManager / E-mail | — | A confirmar |
| **NOC / GE** | Verificação local na fábrica, impressoras | DeskManager (Central de Serviços) | — | 24x7 |
| **Carlos Favacho** | Portal RH Cloud (resposta HTTP) | Teams / DeskManager | — | A confirmar |

## 📋 Catálogo por categoria

### 🖥️ Infraestrutura & Redes

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `/: Disk space is critically low` | 🔴 | Zabbix-Proxy | Abrir ou transferir chamado solicitando liberação de espaço. | Infraestrutura · DeskManager | ⏱️ Imediato |
| `sda: Disk read/write responses too high` | 🟠 | Zabbix-Proxy | Abrir chamado. Sem resposta, acionar no Teams. | Infraestrutura · DeskManager → Teams | ⏱️ Imediato |
| `ICMP: Unavailable by ICMP ping` | 🟠 | Impressora HP | Verificar presencialmente na fábrica e abrir chamado. | NOC / GE · Central de Serviços | ⏱️ Imediato |
| `Portas RDP 10.0.20.217 e 10.0.10.25 fora` | 🟠 | Banpará | Validar no MSMonitor/Zabbix e testar com ping e telnet. | NOC | ⏱️ Imediato |
| `/: Disk space is low (used > 80%)` | 🟡 | Wazuh SIEM | Abrir chamado informando o alerta e o host afetado. | Infraestrutura · DeskManager | ⏱️ Imediato |
| `For passive only agents...` | 🟡 | Wazuh SIEM | Transferir para a Infraestrutura (chamado teste do setor). | NOC / Infra · DeskManager | ⏱️ Imediato |
| `Toner Magenta abaixo de 5%` | 🟡 | Impressora HP | Solicitar substituição e fazer teste de impressão após a troca. | NOC / GE · Central de Serviços | ⏱️ Imediato |
| `High ICMP ping loss` | 🟡 | AP REUNIAO [Ubiquiti] | Abrir chamado. Sem resposta, acionar no Teams. | Infraestrutura · DeskManager → Teams | ⏱️ 7 min (5m + 2m) |
| `Interface VPNBKP(): Baixo Tráfego` | 🟡 | Proxy [Fortigate] | Abrir chamado. Sem resposta, acionar no Teams. | Infraestrutura · DeskManager → Teams | ⏱️ 7 min (5m + 2m) |
| `Link down / Ethernet lower speed` | 🟡 | AP | Abrir chamado. Sem resposta, acionar no Teams. | Infraestrutura · DeskManager → Teams | ⏱️ 12 min (10m + 2m) |

#### Referência técnica — Infraestrutura & Redes

| Alerta | Descrição | Causa provável | Referência |
| :--- | :--- | :--- | :--- |
| `/: Disk space is critically low` | Espaço da partição raiz em nível crítico. Tende a durar dias até a intervenção. | Crescimento de logs ou arquivos temporários. | Ref: 0726-001673 |
| `sda: Disk read/write responses too high` | Tempo de espera (await) muito alto no disco do servidor da fábrica. | Gargalo de I/O no disco. | — |
| `ICMP: Unavailable by ICMP ping` | Impressora inacessível na rede da fábrica. | Equipamento desligado ou falha de rede. | — |
| `Portas RDP 10.0.20.217 e 10.0.10.25 fora` | Afeta acessos da equipe de Crédito/Sustentação (24x7). | Falha de conectividade com o banco. | — |
| `/: Disk space is low (used > 80%)` | Espaço da partição raiz (/) acima de 80%. | Geração excessiva de logs pelo firewall. | — |
| `For passive only agents...` | Zabbix Agent parado ou host indisponível. | Falha de rede ou porta 10050 bloqueada. | — |
| `Toner Magenta abaixo de 5%` | Baixa qualidade de impressão por falta de suprimento. | Fim da vida útil do toner. | — |
| `High ICMP ping loss` | Perda de pacotes na comunicação com o AP. | Intermitência wireless (AirOS). | — |
| `Interface VPNBKP(): Baixo Tráfego` | Tráfego abaixo do normal na VPN de backup. | Intermitência IPsec. | — |
| `Link down / Ethernet lower speed` | Queda de link ou degradação na velocidade de negociação. | Falha física de cabo ou porta. | — |

### 🔐 Segurança (SOC)

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `ONESecure: Ticket aberto [xxxxxx]` | 🔴 | OneSecure | Realizar a triagem N1, coletar evidências obrigatórias, abrir chamado e encaminhar para a fila do SOC. | SOC · DeskManager / Teams | ⏱️ Imediato |
| `OneSecure: API Indisponível` | 🟠 | OneSecure | Validar no link de status. Se persistir por mais de 5 min, abrir chamado com evidências e horários. | SOC · DeskManager / Teams | ⏱️ 5 min |

#### Referência técnica — Segurança (SOC)

| Alerta | Descrição | Causa provável | Referência |
| :--- | :--- | :--- | :--- |
| `ONESecure: Ticket aberto [xxxxxx]` | Incidente de segurança classificado como Alto (rule.level 12-14) ou Crítico (15+). N1 faz triagem; investigação é do SOC. | Detecção do SIEM. | Procedimento N1 — Triagem ONESecure |
| `OneSecure: API Indisponível` | API da plataforma ONESecure sem resposta. | Instabilidade da plataforma. | Página de Status do SOC |

### 💾 Banco de Dados & Oracle

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `Job [STP_PROCESSA_PEDIDO] (Ended Not OK)` | 🟠 | Control-M | Informar ODate, código do pedido e erro. Verificar instabilidade externa do FLASH. | Suporte Oracle · DeskManager | ⏱️ Imediato |
| `RotinaComFalha` | 🟠 | RH Cloud | Se o erro mudar na reexecução, não abrir chamado duplicado: vincular ao existente. | Suporte Oracle · DeskManager | ⏱️ Imediato |
| `CargaComFalha` | 🟠 | RH Cloud | Transferir chamado informando o erro. | Suporte Oracle · DeskManager | ⏱️ Imediato |

#### Referência técnica — Banco de Dados & Oracle

| Alerta | Descrição | Causa provável | Referência |
| :--- | :--- | :--- | :--- |
| `Job [STP_PROCESSA_PEDIDO] (Ended Not OK)` | Falha na proc VIBE_LJ.STP_PROCESSA_PEDIDO com Exit Code 20000. | HTTP 502 / Status 400 retornado pelo provedor FLASH. | — |
| `RotinaComFalha` | Falha na execução da rotina de RH. | Erros diversos do sistema. | — |
| `CargaComFalha` | Falha de carga sistêmica. | Erros diversos do sistema. | — |

### 🏢 Aplicações & RH

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `PagamentoNegativo` | 🟠 | RH Cloud | Enviar e-mail para o setor e buscar histórico de casos similares. | Administrativo · E-mail | ⏱️ Imediato |
| `PagamentoNãoProcessado` | 🟠 | RH Cloud | Transferir chamado relatando o erro sistêmico. | Administrativo · DeskManager | ⏱️ Imediato |
| `PagamentoNãoConciliado` | 🟠 | RH Cloud | Transferir chamado relatando a divergência. | Administrativo · DeskManager | ⏱️ Imediato |
| `Http Response - Portal RH Cloud` | 🟡 | Ferramentas Int. | Reportar a instabilidade do Portal. | Carlos Favacho · Teams / DeskManager | ⏱️ Imediato |
| `Http response - Feedz` | 🟡 | Ferramentas Int. | Abrir chamado. Sem resposta, acionar no Teams. | Infraestrutura · DeskManager → Teams | ⏱️ Imediato |
| `BenefícioNãoDisponibilizado` | 🟡 | RH Cloud | Criar chamado reportando a falha de integração e transferir. | RH · DeskManager | ⏱️ Imediato |
| `ColaboradorNãoAtivado` | 🟡 | RH Cloud | Transferir chamado informando a matrícula afetada. | RH · DeskManager | ⏱️ Imediato |
| `CentroDeCustoIncompleto` | 🔵 | RH Cloud | Transferir chamado para o setor competente. | Administrativo · DeskManager | ⏱️ Imediato |

#### Referência técnica — Aplicações & RH

| Alerta | Descrição | Causa provável | Referência |
| :--- | :--- | :--- | :--- |
| `PagamentoNegativo` | Contracheque com saldo negativo. | Erro de cálculo. | — |
| `PagamentoNãoProcessado` | Falha sistêmica no fluxo de pagamento. | Causa desconhecida. | — |
| `PagamentoNãoConciliado` | Falha na conciliação dos valores. | Causa desconhecida. | — |
| `Http Response - Portal RH Cloud` | Erro na resposta HTTP. | Causa não informada. | — |
| `Http response - Feedz` | Instabilidade na plataforma Feedz. | Falha de conexão externa. | — |
| `BenefícioNãoDisponibilizado` | Benefício do funcionário não foi disponibilizado. | Causa desconhecida. | — |
| `ColaboradorNãoAtivado` | Contratação iniciada, mas o perfil segue inativo. | Fluxo de ativação travado. | — |
| `CentroDeCustoIncompleto` | Colaborador com centro de custo em 0%. | Cadastro incompleto. | — |

### 🔗 Monitoramento & Integrações

| Alerta | Sev. | Host | Ação imediata do operador | Fila / Contato | Escalonar em |
| :--- | :---: | :--- | :--- | :--- | :--- |
| `Erro na sincronização de integração` | 🟠 | MSMonitor | Aguardar a mensagem de "normalizada". Se persistir, ligar para o plantão. | Sobreaviso MSMonitor · Telefone (Jordy) | ⏱️ Imediato |
| `STALL` | 🟠 | MSMonitor | Aguardar a recuperação automática. Se persistir, acionar o plantão. | Sobreaviso MSMonitor · Telefone (Jordy) | ⏱️ Imediato |
| `Connection prematurely closed BEFORE response` | 🟠 | Grafana Integration | Aguardar o tempo limite. Se não normalizar, abrir chamado. | Suporte DEV · DeskManager | ⏱️ 7 min (5m + 2m) |
| `Falha na conexão ao executar operação` | 🟠 | Zabbix Integration | Aguardar o tempo limite. Se não normalizar, abrir chamado. | Suporte DEV · DeskManager | ⏱️ 7 min (5m + 2m) |

#### Referência técnica — Monitoramento & Integrações

| Alerta | Descrição | Causa provável | Referência |
| :--- | :--- | :--- | :--- |
| `Erro na sincronização de integração` | Erro ao carregar alertas (ex.: zabb, id 12). | Falha no getAlerts com o Zabbix. | — |
| `STALL` | Nenhum arquivo de alerta recebido em N verificações. | Coletor parado (ex.: cliente Votorantim). | — |
| `Connection prematurely closed BEFORE response` | Conexão encerrada com a API do Grafana. | Instabilidade de rede/API. | — |
| `Falha na conexão ao executar operação` | MSMonitor falhando ao se conectar na API do Zabbix. | Instabilidade de rede/API. | — |
