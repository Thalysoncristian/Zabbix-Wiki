# Matriz de escalonamento e fluxo de atendimento

Fonte: catálogo operacional colado pelo usuário em 2026-09-05 ("Wiki Manual -
alertas .md" — conteúdo real de NOC, não gerado pela coleta). Este arquivo é a
referência central que as fichas em `docs/alerts/*.json` apontam pelo campo
`operational.notes`, para não repetir a tabela inteira em cada ficha.

> **Regra de ouro:** nenhum acionamento por Teams ou telefone acontece sem
> chamado aberto e evidência coletada (host, horário, print/output). O SLA só
> começa a contar depois do chamado registrado.

## Fluxo de atendimento

```
Alerta recebido
  -> severidade Baixa/Média: aguardar a tolerância do alerta
       -> normalizou sozinho? sim: registrar no plantão e encerrar
                              não: seguir para validação
  -> severidade Alta/Crítica: validar imediatamente
  -> coletar evidências (host, data/hora, print, output)
  -> abrir chamado no DeskManager
  -> transferir para a fila responsável
  -> houve retorno dentro do SLA? sim: acompanhar até normalizar
                                  não: escalonar (Teams ou telefone do sobreaviso)
```

## Severidade e tolerância

| Severidade | Postura esperada |
|---|---|
| Crítica | Validar e abrir chamado na hora. Comunicar o plantão. |
| Alta | Validar e abrir chamado na hora. |
| Média | Respeitar a tolerância do alerta antes de abrir. |
| Baixa | Registrar e transferir sem urgência. |

Como ler o SLA: `7 min (5m + 2m)` = 5 minutos de tolerância para o alerta se
normalizar sozinho **+** 2 minutos de espera pelo retorno do chamado antes de
escalonar pelo Teams. `Imediato` = abrir o chamado assim que o alerta for
validado.

## Matriz de acionamento

| Fila / Time | Responsável por | Canal primário | Escalonamento | Horário |
|---|---|---|---|---|
| **Infraestrutura** | Rede, links, APs, VPN, disco, servidores | DeskManager | Teams — Rafael Sales | A confirmar |
| **SOC** | Incidentes de segurança, ONESecure | DeskManager → fila SOC | Teams (analista) | Acionamento direto **somente em horário comercial** |
| **Suporte Oracle** | Procedures, RH Cloud, cargas e rotinas | DeskManager | — | A confirmar |
| **Suporte BMC** | Control-M e integração Control-M ↔ Oracle | DeskManager | — | A confirmar |
| **Suporte DEV** | Integrações MSMonitor (Grafana / Zabbix API) | DeskManager | — | A confirmar |
| **Sobreaviso MSMonitor** | Coletores e sincronização MSMonitor | Telefone — Jordy (91) 99165-4121 | — | Plantão |
| **RH** | Benefícios, ativação de colaborador | DeskManager | — | A confirmar |
| **Administrativo** | Pagamentos, centro de custo | DeskManager / E-mail | — | A confirmar |
| **NOC / GE** | Verificação local na fábrica, impressoras | DeskManager (Central de Serviços) | — | 24x7 |
| **Carlos Favacho** | Portal RH Cloud (resposta HTTP) | Teams / DeskManager | — | A confirmar |

Os campos **A confirmar** precisam ser validados com cada time — eles vieram
assim na fonte original e não foram inventados aqui.

## Onde procurar o alerta

| Se o alerta veio de... | Categoria |
|---|---|
| Wazuh SIEM, Zabbix-Proxy, AP, Fortigate, impressora, Banpará | Infraestrutura & Redes |
| ONESecure | Segurança (SOC) |
| Control-M, RH Cloud (rotina / carga) | Banco de Dados & Oracle |
| RH Cloud (pagamento, benefício, cadastro), Feedz, Portal RH | Aplicações & RH |
| MSMonitor, Grafana Integration, Zabbix Integration | Monitoramento & Integrações |
| Job Control-M do tipo *Database Oracle* | VibeCloud |

## Matriz específica — Chubb (Control-M SaaS)

Fonte: manual "Control-M SaaS Chubb" colado pelo usuário em 2026-09-06. Regras
próprias deste cliente, além da matriz geral acima — não confundir contatos.

| Serviço / Alerta | Fila | Responsável técnico | Ação inicial | Nível |
|---|---|---|---|---|
| Zabbix — infraestrutura/serviços | NOC | NOC | Registrar, validar impacto, acionar responsável | N1 |
| Control-M — falha de job / agente indisponível | Suporte BMC | Bruno Mendes | Analisar log, reexecutar (máx. 3x), escalar | N2 (**ver dúvida abaixo**) |
| Control-M — Long Run (qualquer job) | Suporte BMC | Bruno Mendes / João Vitor Queiroz | Acompanhar até 10 min antes de agir | N1/N2 |
| Azure (App Enel) — indisponibilidade | Suporte DEV | João Vitor Queiroz | Validar, reiniciar Azure Function, coletar evidências | N2 |
| API ENEL — indisponibilidade externa | NOC → e-mail Chubb | Time Chubb | Enviar evidências por e-mail | N2 |

**Contatos — Chubb:**
Mayara Polonio (Mayara.Polonio@Chubb.com) · Gabriel Chakrian (Gabriel.chakrian@chubb.com) ·
Jajyta Biadolla (jajyta.biadolla@chubb.com) · Priscila Costa (priscila.costa@chubb.com)

**Contatos — Vibe Tecnologia:**
João Queiroz — Azure, analista interno (joao.queiroz@vibetecnologia.com, deve ser copiado nas análises) ·
Marcos Paulo Pinheiro Correa — Control-M, acionamento crítico (**telefone não informado na fonte**) ·
Bruno Rezegue Mendes — Control-M, acionamento crítico, (91) 98298-4301 ·
E-mail de fila: controlm-saas@vibetecnologia.com

**Regra de escalonamento:** contato direto com a Chubb só é permitido para API/FTP
indisponível. Para tudo mais, tratar internamente N1 → N2 antes de qualquer
comunicação externa.

**Regra específica de Long Run — step `TransfereArquivoChubb_Conciliado`:**
verificar no Azure Storage (container `arquivos`) se o arquivo conciliado foi
gerado *antes* de interromper ou reexecutar o step. Se não foi gerado, analisar
e escalar; se foi gerado, pode parar e reexecutar — nunca ao contrário.

**Dúvidas abertas na fonte, não resolvidas por mim:**
- Quem reexecuta jobs do Control-M na prática — N1 (NOC, "quando permitido",
  segundo o texto geral) ou N2 (Bruno Mendes, segundo a seção específica e a
  matriz)? O documento se contradiz nos dois lugares.
- Marcos Paulo consta como contato crítico sem telefone — se o Bruno não
  atender, não há segundo número pra ligar.
- "Prioridade de normalização até as 08:00" não tem uma regra de escalonamento
  amarrada a esse horário.

## Rastreabilidade — de onde veio cada ficha

As fichas abaixo foram preenchidas a partir deste catálogo. `zabbix` marca o
que existe no snapshot coletado (`output/snapshots/20260905_181510`); `manual`
marca o que não tem trigger correspondente hoje (aplicações próprias —
RH Cloud, MSMonitor — que não são monitoradas via Zabbix).

| Ficha | Origem |
|---|---|
| `lld__vibe-zabbix-proxy__vfs-fs-...critically-low...json` | zabbix |
| `lld__vibe-zabbix-proxy__vfs-dev-...too-high...json` | zabbix |
| `rule__linux-zabbix-agent-is-not-available...json` | zabbix |
| `lld__vibe-wazuh-siem__vfs-fs-...disk-space-is-low...json` | zabbix |
| `rule__icmp-unavailable-by-icmp-ping...json` (Impressora HP) | zabbix |
| `rule__toner-*-abaixo-de-5...json` (4 cores) | zabbix |
| `rule__porta-rdp-10-0-20-217-fora...json` | zabbix |
| `rule__porta-rdp-10-0-20-25-fora...json` | zabbix — **divergência**: fonte original citava `10.0.10.25`, o ambiente real usa `10.0.20.25` |
| `rule__ubiquiti-airos-high-icmp-ping-loss...json` (AP REUNIAO) | zabbix |
| `rule__fortigate-interface-vpnbkp-baixo-trafego...json` | zabbix |
| `rule__onesecure-api-indisponivel...json` | zabbix |
| `rule__http-response-portal-rh-cloud...json` | zabbix |
| `rule__http-response-feedz...json` + variante `failed-step-of-scenario` | zabbix |
| `rule__control-m-in01--job.json` | zabbix (regra, agrega vários jobs) |
| `rule__master-support--security.json` | zabbix (regra — triagem N1 completa) |
| `manual__rh-cloud-*.json` (8 fichas) | manual — RH Cloud não aparece no Zabbix coletado |
| `manual__msmonitor-*.json`, `manual__grafana-integration-*.json`, `manual__zabbix-integration-*.json` | manual — MSMonitor não aparece no Zabbix coletado |
| `rule__api-enel-token-autenticador-indisponivel...json` | zabbix (host Chubb - Links de API) |
| `lld__chubb-links-de-api__autorization-enel-api__enel-api-*...json` (8 fichas) | zabbix |
| `lld__chubb-links-de-api__autorization-enel-api__arquivo-*...json` (5 fichas) | zabbix — **inferido**, o manual não cita esses alertas nominalmente |
| `rule__api-vibe-processamento-indisponivel...json`, `rule__ftp-chubb-*...json` (3), `rule__ssh-chubb-*...json` | zabbix — **gap real**: alertas existem no host, sem procedimento no manual |
| `rule__control-m-in01--job.json` | atualizada — exceção do job `TransfereArquivoChubb` (Chubb) adicionada dentro da regra, não como override (o `alert_key` desse job muda todo dia por causa do `ODate`) |
