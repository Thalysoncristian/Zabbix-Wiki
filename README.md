# Base de Conhecimento Operacional de Alertas Zabbix

Transformar os alertas do Zabbix em uma base de conhecimento que responda, às 03h17
da madrugada, o que o operador precisa saber: *o que é esse alerta, o que verificar,
espero ou ajo, abro chamado, para qual fila, quem é o responsável agora, qual o SLA,
quando escalar e como sei que resolveu.*

O desenvolvimento é **incremental**. Este repositório está na **ETAPA 2**.

```
   ETAPA 1  coletar os alertas reais do Zabbix e validar os dados   ✓ concluída
>> ETAPA 2  modelo operacional completo + fichas em docs/alerts/   <<  VOCÊ ESTÁ AQUI
   ETAPA 3  núcleo do sistema e persistência
   ETAPA 4  interface web + dashboard + fichas
   ETAPA 5  alertas manuais
   ETAPA 6  importação da wiki existente
   ETAPA 7  regras de horário / madrugada / responsáveis
   ETAPA 8  sugestões de IA
   ETAPA 9  exportação consolidada
   ETAPA 10 geração da wiki a partir dos JSONs validados
```

**Ainda não existe** (e não deve existir) nesta etapa: FastAPI, HTML, dashboard,
banco de dados, IA, importação de wiki, `schedule.yaml`, `categories.yaml`.
Primeiro os dados reais; depois as camadas de cima.

## A ficha operacional (ETAPA 2)

Cada alerta vira um JSON em `docs/alerts/` com três áreas de responsabilidade
**separadas de propósito**:

| Bloco | O que é | Quem escreve |
|---|---|---|
| `zabbix` | fato técnico | a coleta, sempre; ninguém edita à mão |
| `ai_suggestion` | sugestão | a IA (ETAPA 8) — nunca decide |
| `operational` | procedimento oficial | **só humano** |

A IA nunca escreve em `operational`. Uma sugestão pode ser copiada para a ficha
por uma pessoa, mas a aprovação continua humana.

### Nível da ficha: família e override

Decisão que veio dos dados reais. Numa coleta de produção, 1.229 de 1.380
alertas vinham de LLD — um alerta por serviço, por ponto de montagem, por
chamado. Documentar um a um é inviável e inútil: o procedimento é o mesmo para
a família inteira.

A coleta **sempre** gera ficha de família. Instância é um override criado por
uma pessoa, quando um caso específico foge da regra:

```
family    lld|windows-bob|service-discovery|service-name-is-not-running
          "qualquer serviço do Windows parado" — 1 ficha cobre 62 serviços

family    rule|cortex-arquivo-de-log-maior-que-100mb|a1b2c3d4
          trigger escrito à mão — 1 ficha, hoje com 1 instância

override  override|srv-prod-01|disk-space-low
          "neste host o procedimento é outro" — só humano cria
```

O nível **nunca** é inferido por contagem de instâncias. Se fosse, um LLD que
descobrisse um ponto de montagem novo transformaria a ficha de instância em
ficha de família, com outra chave — e a documentação já escrita ficaria órfã.
O operador às 3h buscaria o alerta e cairia numa ficha vazia. Esse bug existiu
e está coberto por teste de regressão
(`test_instancia_nova_nao_muda_a_chave_nem_abandona_a_documentacao`).

Numa simulação com o padrão real do ambiente, **1.121 alertas geraram 8
fichas**.

### `python main.py reconcile`

Aplica um snapshot da coleta sobre as fichas existentes. O que ele **nunca**
faz: apagar documentação humana, sobrescrever `operational`, ou rebaixar o
status por conta própria.

```
alerta novo no Zabbix   →  cria ficha `undocumented`   (🆕 novo alerta)
fato técnico mudou      →  documented/reviewed → `review_needed`
alerta sumiu da coleta  →  `present_in_zabbix: false`, ficha preservada
alerta voltou           →  marcado presente de novo
```

A comparação usa `source_hash` — só o fato técnico. Editar a ficha nunca
dispara `review_needed`, e recriar o trigger no Zabbix (novo `triggerid`) nunca
faz a documentação ser perdida, porque a identidade é a `alert_key`.

A comparação usa um hash da família, calculado só sobre o que define a regra
(descrição do protótipo, regra de descoberta, severidade, tags). Assim, um
chamado que fecha ou um serviço recém-descoberto trocam as instâncias sem pedir
revisão de nada — só uma mudança na regra em si pede.

Coletando grupo a grupo, passe o filtro: o `reconcile` lê o escopo do próprio
snapshot e só avalia como "sumidas" as fichas daquele escopo — senão coletar um
grupo marcaria todos os outros como desaparecidos.

### Máquina de estados

```
undocumented → pending_review → documented → reviewed
                                    │            │
                                    └─────┬──────┘
                                          ↓
                                   review_needed        (o Zabbix mudou)
```

`not_applicable` é alcançável de qualquer estado. Marcar como `documented`
exige campos mínimos — `meaning`, `requires_ticket`, `resolution_criteria`, e
equipe + fila quando abre chamado. É o que impede salvar um rascunho e fingir
que o alerta está documentado.

### Concorrência

Cada ficha tem `revision`, que avança a cada gravação. Salvar com uma revisão
desatualizada é recusado:

```
⚠ Esta ficha foi alterada por outra pessoa em 03:02 (revisão 4; você carregou a 3).
  Recarregue a ficha antes de salvar novamente.
```

Timestamp sozinho não serve: `last_modified_at` com precisão de segundo não
distingue duas gravações no mesmo segundo — exatamente o caso de duas pessoas
editando a mesma ficha às 03h.

### Nome dos arquivos

A `alert_key` usa `|`, que é inválido em nome de arquivo no Windows, e as
descrições de LLD passam de 100 caracteres. O nome é sanitizado (`|` → `__`),
truncado com sufixo de hash quando necessário, e nomes reservados do Windows
(`CON`, `LPT1`…) são escapados. A chave verdadeira vive dentro do JSON — o
arquivo é só o endereço.

---

## 1. O que a ETAPA 1 entrega

1. Autenticação no Zabbix (**API token** preferencialmente; usuário/senha como fallback).
2. Coleta dos **triggers** (com expressão expandida).
3. Resolução dos **hosts** relacionados.
4. Resolução dos **host groups** (nomes).
5. Resolução dos **templates** (nomes) e do **template de origem** do trigger.
6. Resolução apenas dos **itens que alimentam cada trigger**.
7. Resolução das **dependências** entre triggers (com nomes).
8. **Snapshot bruto imutável** por execução.
9. **Alertas normalizados** e autocontidos, com `alert_key` e `source_hash`.
10. **Relatório da coleta**, incluindo análise de colisões de `alert_key`.

### Somente leitura — garantido no código

O cliente possui uma *allowlist fechada* de métodos (`src/zabbix_client.py`):

```
apiinfo.version   trigger.get   host.get   hostgroup.get   template.get
item.get          triggerprototype.get
```

Qualquer outro método levanta `ReadOnlyViolationError` **antes** de qualquer
requisição HTTP. Não existe no código nenhuma chamada de escrita
(`trigger.create/update/delete`, `host.create/update/delete`, `item.create/update`, …),
e há um teste automatizado que varre `src/` procurando por elas
(`tests/test_readonly.py`).

`user.login` / `user.logout` só são liberados quando você opta pelo fallback de
usuário/senha — elas apenas abrem/encerram uma sessão e não alteram dados de
monitoramento. Usando API token, ficam bloqueadas também.

---

## 2. Requisitos

* Python 3.10+
* Acesso HTTPS à API do Zabbix (`/api_jsonrpc.php`)
* Um usuário/token **somente leitura** no Zabbix
* Zabbix 5.4+ (testado logicamente contra 6.0 e 7.0; há tratamento de diferenças
  de versão para `selectHostGroups`/`selectGroups`, `name_resolved` e para o
  estilo de autenticação)

### Permissões recomendadas no Zabbix

Crie um usuário de papel **User** (ou *role* customizada sem permissões de escrita)
com acesso de **leitura** aos grupos de hosts que você quer documentar, e gere um
token em **Administração → Geral → Tokens de API**.

---

## 3. Instalação

```bash
git clone <este-repositorio>
cd Zabbix-Wiki

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
$EDITOR .env
```

`.env` mínimo:

```env
ZABBIX_URL=https://zabbix.suaempresa.com.br
ZABBIX_API_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

O `.env` **nunca** é versionado (está no `.gitignore`). Nenhuma credencial aparece
no código, nos logs ou nos snapshots.

Variáveis opcionais: `ZABBIX_VERIFY_TLS` (`true` | `false` | caminho do CA bundle),
`ZABBIX_TIMEOUT`, `ZABBIX_PAGE_SIZE`, `ZABBIX_TRIGGER_BATCH_SIZE`,
`ZABBIX_MAX_RETRIES`, `ZABBIX_RETRY_BACKOFF`, `ZABBIX_MIN_PAGE_SIZE`,
`ZABBIX_HOST_GROUPS`, `OUTPUT_DIR`. As três de retry/página estão explicadas na
seção [13. Escala da coleta](#13-escala-da-coleta).

---

## 4. Uso

```bash
# testa conexão e credenciais, sem coletar nada
python main.py check

# aplica a última coleta sobre as fichas em docs/alerts/
python main.py reconcile

# simula, sem gravar nada
python main.py reconcile --dry-run

# cobertura da documentação
python main.py status

# coleta do ambiente inteiro (percorre grupo a grupo, nunca numa requisição só)
python main.py collect

# coleta reduzida, para a primeira validação
python main.py collect --limit 50 --examples 3

# um grupo de hosts
python main.py collect --host-group "Vibe Tecnologia"

# vários grupos — repetindo a flag ou separando por vírgula
python main.py collect --host-group "Vibe Tecnologia" --host-group "Zabbix servers"
python main.py collect --host-group "Vibe Tecnologia,Zabbix servers"

# página menor, para servidores que recusam lotes grandes
python main.py collect --host-group "Vibe Tecnologia" --page-size 100

# um snapshot independente por grupo, consolidado ao final
python main.py collect --host-group "Vibe Tecnologia,Zabbix servers" --split-by-group --merge

# consolida coletas feitas em dias diferentes
python main.py merge
python main.py merge --last 3
python main.py merge output/snapshots/2026*__vibe-tecnologia output/snapshots/2026*__zabbix-servers

# apenas triggers habilitados em hosts monitorados
python main.py collect --only-monitored

# interface web local (Fase 3) — abre em http://127.0.0.1:8000
python main.py serve
python main.py serve --port 9000
python main.py serve --snapshot output/snapshots/20260905_181510
```

Opções de `collect`: `--limit`, `--host-group` (repetível ou com vírgulas),
`--page-size N`, `--split-by-group`, `--merge`, `--resume`, `--only-monitored`,
`--include-template-triggers`, `--full`, `--examples N`, `--output DIR`.
Opções de `merge`: caminhos de snapshot posicionais, `--last N`, `--output DIR`.
Opções de `serve`: `--host`, `--port`, `--snapshot`, `--output DIR`, `--docs-dir DIR`.
Opções globais (antes do subcomando): `--env-file ARQUIVO`, `-v/--verbose` —
ex.: `python main.py --env-file .env.homolog collect`.

### Quanto a coleta fala

Numa coleta real de 18.903 triggers, uma linha por página são 203 linhas e o
relatório detalhado passa de 130. O padrão é enxuto (~28 linhas):

| | progresso | relatório |
|---|---|---|
| padrão | uma linha por **fase**, atualizada no lugar | resumo: contagens, top 3 famílias, colisões em uma linha cada |
| `--full` | — | detalhamento completo, com ocorrências e expressões |
| `-v` | uma linha por **página** | — |
| `--examples N` | — | + N alertas normalizados inteiros (~80 linhas de JSON cada) |

Avisos (lote reduzido, objeto não coletado) aparecem em **todos** os modos.
Silenciar um problema para caber na tela seria o pior dos dois mundos. E os
arquivos do snapshot têm sempre tudo — o que muda é só o que vai para a tela.

Por padrão são coletados os triggers **dos hosts** (`templated=false`) — que é o que
gera alerta de verdade. O trigger do template é alcançado pela cadeia `templateid`
para servir de escopo da chave.

Como a coleta aguenta um ambiente de dezenas de milhares de triggers está
descrito na seção [13. Escala da coleta](#13-escala-da-coleta).

### Saída esperada

```
✓ Conectado ao Zabbix (API 7.2.1, api_token (Authorization: Bearer))
✓ Escopo da coleta : ambiente inteiro
✓ Hosts no escopo  : 82
✓ 18903 triggers encontrados
✓ 78 hosts · 21 grupos · 0 templates · 9965 itens
✓ 18826 alertas únicos em 469 famílias
✓ 32 possíveis colisões de alert_key

  origem   : prototype+description=18366, host+description=537
  lacunas  : 16506 sem comentário, 179 sem tags, 1000 com dependências
  severidade: Information=17546, Warning=510, Average=342, High=292, Disaster=157

── Famílias — 469 procedimentos cobririam 18903 alertas ──
    8131 alertas  {#JOBID} - Job: {#NAME} - Ended Not Ok  [LLD: Jobs]
     277 alertas  {#CODCHAMADO}: {#ASSUNTO} - Aguardando cliente  [LLD: Atualiza]

── Colisões de alert_key — 32 ──
  ! carguero-api-monitor-down|api-indisponivel  (23 expressões distintas)
  ... e mais 27. Todas em output/snapshots/.../collisions.json

Coleta: 58s, 203 páginas de 250, sem retries nem lotes reduzidos.
```

A linha das **famílias** é a que importa para planejar o trabalho: 469
procedimentos cobrem 18.903 alertas. Use `--full` para o detalhamento e
`--examples N` para ver os JSONs completos.

---

## 5. Estrutura da saída

```
output/
└── snapshots/
    ├── latest -> 20260903_031705__consolidado
    ├── 20260903_030112__vibe-tecnologia/     # coleta de um grupo
    ├── 20260904_025500__zabbix-servers/      # outro grupo, outro dia
    ├── 20260904_031000__siem-parcial/        # coleta interrompida (não é base)
    └── 20260903_031705__consolidado/         # python main.py merge
        ├── raw/
        │   └── zabbix_raw.json      # exatamente o que a API devolveu + log das chamadas
        ├── normalized/
        │   ├── alerts.json          # alertas autocontidos (1 por trigger)
        │   ├── alert_keys.json      # agrupamento por alert_key
        │   └── collisions.json      # colisões detectadas, com detalhes
        └── report.json              # relatório completo da coleta
```

Snapshots **nunca são sobrescritos** — se dois rodarem no mesmo segundo, o segundo
recebe sufixo (`..._2`). Isso permite auditoria e comparação histórica, e é o que
torna possível coletar um grupo hoje, outro amanhã e consolidar depois.

O nome do diretório carrega o escopo (`__vibe-tecnologia`, `__consolidado`,
`__amostra`, `...-parcial`), então `ls output/snapshots` já diz o que cada coleta
cobriu sem abrir um único JSON.

---

## 6. O alerta normalizado

Exemplo real gerado pelo pipeline (dados do ambiente de teste offline,
`tests/fixtures/fake_zabbix.py` — com o seu Zabbix o formato é idêntico):

```json
{
  "alert_key": "linux-by-zabbix-agent|linux-disk-space-is-critically-low-used-macro",
  "alert_key_strategy": "template+description",
  "alert_key_scope": { "type": "template", "name": "Linux by Zabbix agent", "id": "10001" },
  "alert_key_basis_description": "Linux: Disk space is critically low (used > {$VFS.FS.PUSED.MAX.CRIT})",
  "alert_key_collision": false,
  "alert_key_suggested": null,
  "scope": "zabbix",
  "zabbix": {
    "triggerid": "100",
    "description_raw": "Linux: Disk space is critically low (used > {$VFS.FS.PUSED.MAX.CRIT})",
    "description_normalized": "linux-disk-space-is-critically-low-used-macro",
    "expression_raw": "{1001}<20",
    "expression_expanded": "last(/srv-linux-01/vfs.fs.size[/,pfree])<20",
    "expression_signature": "last(/{HOST}/vfs.fs.size[/,pfree])<20",
    "recovery_mode": { "value": "0", "name": "expression" },
    "recovery_expression_raw": "",
    "recovery_expression_expanded": "",
    "priority": { "value": "4", "name": "High" },
    "status": { "value": "0", "name": "enabled" },
    "value": { "value": "0", "name": "OK" },
    "state": { "value": "0", "name": "normal" },
    "opdata": "Livre: {ITEM.LASTVALUE1}",
    "event_name": "",
    "comments": "Partição raiz acima do limite configurado.",
    "manual_close": false,
    "templated": true,
    "source_template": "Linux by Zabbix agent",
    "discovered": false,
    "discovery_rule": null,
    "prototype_description": null,
    "dependencies": [],
    "tags": [
      { "tag": "component", "value": "storage" },
      { "tag": "scope", "value": "capacity" }
    ],
    "host": {
      "hostid": "10501",
      "host": "srv-linux-01",
      "name": "Vibe - Zabbix Proxy",
      "status": { "value": "0", "name": "monitored" },
      "inventory": { "os": "Ubuntu 22.04", "location": "DC1" }
    },
    "host_groups": ["Infraestrutura", "Servidores Linux"],
    "templates": ["Linux by Zabbix agent"],
    "items": [
      {
        "itemid": "5001",
        "key_": "vfs.fs.size[/,pfree]",
        "name": "/: Space available in %",
        "units": "%",
        "value_type": { "value": "0", "name": "numeric float" },
        "update_interval": "1m"
      }
    ],
    "zabbix_version": "7.0.0",
    "collected_at": "2026-09-03T21:12:50Z",
    "source_hash": "sha256:64737671bb00c32894d21be6…"
  }
}
```

O JSON é **autocontido**: nomes de host, grupos, templates e itens já vêm
resolvidos. Nenhuma consulta posterior por `hostid=123` / `groupid=45` /
`templateid=77` é necessária para entender o alerta. Os IDs continuam presentes
apenas como referência técnica.

Campos que são enumerações do Zabbix vêm como `{value, name}` — o `value` preserva
o dado bruto, o `name` é o que o operador lê.

---

## 7. `alert_key` — a chave lógica

`triggerid` **não** é identidade de negócio: se o trigger for recriado, o ID muda e
a documentação operacional não pode ser perdida. A chave é derivada de informação
mais estável:

```
<escopo normalizado>|<descrição normalizada>
```

A normalização é determinística: minúsculas, sem acentos, espaços colapsados,
pontuação convertida em hífen, e **macros substituídas por um marcador**
(`{$LIMITE}`, `{HOST.NAME}` → `macro`) quando ainda aparecem cruas na descrição
(triggers de template), para que a chave não dependa de valores que mudam por
host ou por coleta.

O escopo é escolhido do mais estável para o menos estável:

| Prioridade | Estratégia | Quando | Descrição usada na chave | Efeito |
|---|---|---|---|---|
| 1 | `prototype+description` | trigger criado por LLD | a descrição **já expandida do próprio trigger** (não o texto cru do protótipo) | uma chave por entidade descoberta (mount point, serviço…), estável entre redescobertas |
| 2 | `template+description` | trigger herdado de template | a descrição do trigger (ainda com macros, ex. `{$LIMIT}`) | 200 hosts com o mesmo trigger colapsam em **uma** chave |
| 3 | `host+description` | trigger criado direto no host | a descrição do trigger | usa o **host** como escopo |

Exemplo:

```
linux-by-zabbix-agent|linux-disk-space-is-critically-low-used-macro   (template)
linux-by-zabbix-agent|var-disk-space-is-critically-low                (protótipo LLD)
wazuh|wazuh-fila-de-eventos-acima-do-limite                           (host)
```

Isso já prepara a ETAPA 2: **regra genérica** (template) com possibilidade de
**override específico de host**, sem duplicar conhecimento para 200 hosts.

**Por que a estratégia 1 usa a descrição expandida, e não o texto cru do
protótipo:** o texto do protótipo costuma ter mais de uma macro (ex.
`"{#SERVICE.NAME}" ({#SERVICE.DISPLAYNAME}) is not running`, do LLD nativo de
"Windows services discovery"). Como a normalização reduz qualquer `{...}` ao
mesmo marcador, usar o texto cru faria **todos os serviços descobertos em um
host colidirem na mesma chave** — Windows Audio, agente da AWS, firewall —,
apesar de serem alertas com procedimentos completamente diferentes. Isso foi
descoberto rodando a coleta contra um Zabbix real: 50 triggers desse tipo
geraram só 2 chaves, ambas relatadas como colisão. Usar a descrição já
expandida do trigger (que traz o nome real da entidade) resolve o caso sem
comprometer a estratégia de disco, onde o texto expandido (`/var: Disk space…`)
já é, por si só, uma boa base de chave.

### Colisões — o problema não é escondido

Vários triggers compartilharem a mesma `alert_key` **não é colisão** quando são o
mesmo trigger de template em hosts diferentes — é exatamente o objetivo.

São detectados **dois tipos** de colisão:

**`expressoes_diferentes`** — a mesma chave agrupa triggers tecnicamente
distintos. A detecção usa a `expression_signature`: a expressão expandida com o
nome do host trocado por `{HOST}` e as macros por `{MACRO}`. Mesma chave +
assinaturas diferentes = colisão. Caso típico: dois triggers locais chamados
"Serviço parado" monitorando serviços diferentes.

**`escopo_ambiguo`** — a chave tem escopo de **host** mas agrupa hostids
distintos: dois hosts diferentes cujos nomes produzem o mesmo slug (ex.
`Vibe - Zabbix-Proxy` e `Vibe - Zabbix Proxy`). Esse caso escaparia da checagem
por assinatura, porque a assinatura troca o host por `{HOST}` justamente para
permitir que hosts diferentes compartilhem a chave de um template. Aqui a
sugestão desambigua pelo nome técnico exato do host
(`<escopo>#<sha256(host)[:8]>|<descrição>`).

**`duplicado_no_host`** — a mesma chave agrupa triggers **distintos no mesmo
host**. Sempre suspeito: como a assinatura troca macros por `{MACRO}`, dois
triggers que diferem só no limiar ficam com assinatura idêntica e se fundiriam
em silêncio — dois procedimentos virando uma ficha.

O caso mais comum **não é erro de configuração**: é o par avisar/agir do
próprio Zabbix — o mesmo item em dois limiares e duas severidades
(`{$EXP_WARN}` em Warning, `{$EXP_CRIT}` em High). São procedimentos
diferentes de verdade (um espera, o outro age), então a chave sugerida usa a
severidade: `<chave>@warning` e `<chave>@high`. Legível e estável.

A severidade só é usada quando os triggers medem o **mesmo item**. Se os itens
diferem, a diferença real não é o limiar — são alertas distintos e a chave
sugerida volta a ser o hash da expressão. Quando nem item nem severidade
separam os triggers, o relatório mostra triggerid e severidade de cada um e
deixa a decisão para o humano: aí sim costuma ser duplicidade a corrigir no
Zabbix.

Cada colisão é relatada no console, em `normalized/collisions.json` e em
`report.json`, com host, descrição e expressão de cada ocorrência. O alerta afetado
recebe:

```json
"alert_key_collision": true,
"alert_key_suggested": "wazuh|servico-parado#03e1cb22"
```

**Estratégia proposta** quando houver colisão: sufixar a chave com
`#sha256(expression_signature)[:8]`, que é determinístico e sobrevive à recriação
do trigger (o `triggerid` muda, a expressão não). A chave primária **não é alterada
automaticamente** — a decisão é humana, e vem na ETAPA 2. Um caso típico e legítimo
de colisão é descrição genérica demais ("Serviço parado") em triggers locais
diferentes; a resposta certa costuma ser corrigir a descrição no Zabbix.

Rode a coleta e verifique `report.json` → seção `collisions` antes de aprovar a etapa.

---

### Famílias de alertas — o nível em que o procedimento é único

Uma regra de LLD produz um alerta por entidade descoberta: 300 serviços do
Windows, 40 pontos de montagem, 12 certificados. Cada um precisa de chave
própria (saber *qual* serviço caiu importa), mas o **procedimento** costuma ser
o mesmo da família inteira.

O relatório agrupa os alertas em famílias — o protótipo de LLD para alertas
descobertos, a regra inferida para os demais — e mostra quantas existem. É a
diferença entre "1.380 fichas para escrever" e "algumas dezenas de
procedimentos, com exceções pontuais". Insumo direto para o desenho da ETAPA 2.

### Sem acesso a templates: regras genéricas inferidas

No Zabbix, o acesso a templates é concedido por **grupos de templates** e exige
usuário do tipo **Admin** — falta com frequência em credenciais somente leitura.
Quando isso acontece, `template.get` devolve 0, nenhum trigger é reconhecido
como herdado e **todo alerta vira específico do host**: o mesmo procedimento
seria documentado 82 vezes em um ambiente de 82 hosts.

O relatório mede esse impacto sem depender de permissão. Alertas são agrupados
por `description_normalized` + `expression_signature` (que troca o host por
`{HOST}`): o mesmo trigger aplicado a N hosts cai no mesmo grupo. A seção
*Regras genéricas inferidas* mostra quantos procedimentos distintos existem de
fato e quantas fichas duplicadas o escopo de template evitaria.

Isso serve para dois fins: quantificar o ganho ao pedir a permissão, e servir de
plano B na ETAPA 2 (agrupar por regra inferida) caso a permissão não venha.

## 8. `source_hash` — "o Zabbix mudou o alerta"

SHA-256 determinístico sobre **apenas** os campos técnicos:

```
description_raw · expression_signature · recovery_mode · recovery_expression_signature
priority · opdata · event_name · comments · manual_close · tags
items (key_ | units | value_type) · host · host_groups · templates · source_template
```

**Ficam de fora, propositalmente:**

| Campo | Por quê |
|---|---|
| `triggerid` | muda quando o trigger é recriado, sem mudar o alerta |
| `value` (OK/PROBLEM) | estado de runtime, muda o tempo todo |
| `status` (enabled/disabled) | ligar/desligar não muda o procedimento operacional |
| qualquer conteúdo humano | o bloco `operational` (ETAPA 2) é fonte de verdade humana e nunca entra no hash técnico |

Assim, na ETAPA 2, comparar o `source_hash` gravado no último review com o da coleta
atual responde "o Zabbix mudou o alerta?" sem confundir com "um humano editou a
ficha" — é o gatilho para `documented`/`reviewed` → `review_needed`.

---

## 9. Estrutura do projeto

```
.
├── main.py                    # python main.py collect | check | merge | reconcile | status
├── .env.example
├── requirements.txt
├── src/
│   ├── config.py              # .env -> Settings (parser próprio, sem dependências)
│   ├── zabbix_client.py       # JSON-RPC read-only + allowlist + retry + paginação por IDs
│   ├── collect.py             # orquestra a coleta (escopo -> descoberta -> hidratação)
│   ├── progress.py            # eventos de progresso da coleta
│   ├── merge.py               # consolidação de snapshots independentes
│   ├── normalize.py           # snapshot bruto -> alertas autocontidos
│   ├── keys.py                # alert_key, normalização, source_hash
│   ├── snapshot.py            # escrita imutável em output/snapshots/
│   ├── report.py              # relatório da coleta
│   ├── reconcile.py           # snapshot -> fichas em docs/alerts/
│   ├── core/                  # modelo da ficha, máquina de estados, repositório
│   └── cli.py
└── tests/
    ├── fixtures/fake_zabbix.py      # Zabbix falso (transporte em memória)
    ├── fixtures/flaky_transport.py  # Zabbix que devolve HTTP 500 sob carga
    ├── test_keys.py
    ├── test_readonly.py
    ├── test_normalize.py
    ├── test_pipeline.py
    ├── test_models.py
    ├── test_reconcile.py
    ├── test_scale.py                # paginação, retry, redução de lote, multi-grupo
    ├── test_merge.py                # consolidação e snapshots independentes
    ├── test_cli.py
    └── test_cli_fase2.py
```

Relacionamentos resolvidos pela coleta:

```
trigger ──> item ──> host ──> host group
   │                   └────> template
   ├──> template de origem (cadeia templateid)
   ├──> protótipo LLD (quando o trigger veio de descoberta)
   └──> dependências (com nomes)
```

---

## 10. Testes

O pipeline inteiro é testável **sem um Zabbix real**: `tests/fixtures/fake_zabbix.py`
implementa um transporte JSON-RPC em memória com um ambiente representativo
(trigger de template em 2 hosts, trigger de LLD com protótipo, trigger local e um
par de triggers que colidem de propósito).

`tests/fixtures/flaky_transport.py` complementa: simula o servidor que devolve
`HTTP 500` quando o lote é grande e responde normalmente quando é pequeno — que
é exatamente o comportamento observado no ambiente real de ~19.000 triggers.

```bash
python -m unittest discover -s tests -t .
```

---

## 11. Solução de problemas

| Sintoma | Causa provável / o que fazer |
|---|---|
| `✗ Configuração inválida: ZABBIX_URL não definido` | falta `cp .env.example .env` |
| `Not authorised` | token expirado/revogado, ou usuário sem permissão de leitura no grupo |
| `Falha de TLS` | certificado interno: aponte `ZABBIX_VERIFY_TLS` para o CA bundle (evite `false`) |
| `0 triggers encontrados` | as credenciais não enxergam nenhum grupo de hosts; rode `python main.py check` |
| `Grupos de hosts não encontrados` | o nome em `--host-group` precisa ser exatamente igual ao do Zabbix |
| coleta lenta | use `--host-group` e/ou `--limit` na validação inicial |
| `HTTP 500` com corpo vazio | o servidor Zabbix estourou tempo/memória montando a resposta. O coletor **já trata sozinho**: repete com backoff e divide a página ao meio até o servidor aceitar (aparece como `⚠ lote N recusado — dividindo`). Se ainda assim falhar, baixe `--page-size` (ex.: `--page-size 50`), reduza `ZABBIX_TRIGGER_BATCH_SIZE` e/ou aumente `ZABBIX_TIMEOUT` |
| coleta interrompida no meio | o que já veio é gravado em `..._parcial/` e os snapshots anteriores ficam intactos. Rode de novo com `--resume` para não redescobrir tudo |
| `São necessários ao menos 2 snapshots` | `merge` precisa de duas coletas; rode `collect --host-group` para outro grupo antes |
| `Protótipos de trigger não resolvidos` | o usuário não tem leitura em protótipos; a coleta continua e os triggers de LLD caem na chave por host |
| `0 templates resolvidos` / `templates: []` | as credenciais não enxergam templates. No Zabbix o acesso é dado por **grupos de templates** e costuma faltar em usuários somente leitura. Sem isso nenhum alerta é reconhecido como regra genérica de template e a documentação teria de ser repetida host a host. `python main.py check` avisa quando isso acontece |

---

## 12. Critério de conclusão da ETAPA 1

Execute contra o Zabbix real:

```bash
python main.py collect --examples 3
```

e valide:

- [ ] as contagens do relatório batem com o que você espera do ambiente;
- [ ] `normalized/alerts.json` é compreensível **sem** consultar IDs no Zabbix;
- [ ] as `alert_key` fazem sentido (template x host x LLD);
- [ ] as colisões relatadas em `collisions.json` são reais e a estratégia sugerida serve;
- [ ] nenhuma credencial aparece em `raw/zabbix_raw.json`.

Com isso aprovado, seguimos para a **ETAPA 2** (modelo completo com os blocos
`zabbix` / `ai_suggestion` / `operational`, `docs/alerts/<alert_key>.json`, máquina
de estados de `doc_status` e políticas de horário).

---

## 13. Escala da coleta

O ambiente real tem **~19.000 triggers**. Uma coleta que tentasse trazer isso de
uma vez devolvia `HTTP 500`. A solução não foi aumentar timeout nem limite: foi
mudar como a coleta é feita.

### O caminho da coleta

```
Ambiente
   │  hostgroup.get                       (lista os grupos)
   ▼
Host Groups
   │  host.get { groupids: [um grupo] }   (um grupo por vez, hosts deduplicados)
   ▼
Hosts
   │  trigger.get { hostids: lote,        ← DESCOBERTA: só o ID, sem select*.
   │                output: [triggerid] }    Resposta pequena mesmo com 19k triggers.
   ▼
Lista de IDs  ──────────────────────────► este é o TOTAL REAL do progresso
   │  trigger.get { triggerids: página,   ← HIDRATAÇÃO: output completo + selects,
   │                output+selects }         em páginas de --page-size objetos.
   ▼
Snapshot independente
   │  python main.py merge
   ▼
Base consolidada
```

Nenhuma etapa depende de uma requisição contendo o ambiente inteiro. Um teste
verifica isso diretamente: todo `trigger.get` do log de chamadas precisa carregar
`hostids`, `triggerids`, `groupids` ou `limit`.

### Por que não `limit` / `offset`

A API do Zabbix aceita `limit`, mas **não tem `offset`**. Não existe "próxima
página" nativa: com `limit` sozinho não há como avançar por um conjunto grande.

Paginar por **conjunto de IDs** é o mecanismo equivalente que a API oferece de
fato — e sai melhor em três pontos:

* o total é conhecido antes de começar a parte cara, então a porcentagem do
  progresso é real, não estimada;
* as páginas são determinísticas (IDs ordenados), o que torna a retomada segura;
* uma página que falha pode ser dividida ao meio sem reprocessar o resto.

### Retry, backoff e redução adaptativa de lote

`HTTP 429/500/502/503/504`, timeouts e erros de conexão são tratados como
**transitórios**: o coletor repete com backoff exponencial
(`ZABBIX_RETRY_BACKOFF`, padrão 2s → 4s → 8s → 16s, até `ZABBIX_MAX_RETRIES`).
Erros definitivos — permissão, parâmetro inválido — **não** são repetidos:
insistir só atrasaria o diagnóstico.

Quando as tentativas de uma página acabam, o lote é dividido ao meio e cada
metade é tentada de novo:

```
página de 500 ──✗──> 250 ──✗──> 125 ──✓──> segue
```

A divisão para em `ZABBIX_MIN_PAGE_SIZE` (padrão 25). Uma falha que persiste com
25 IDs é sistemática, e insistir viraria 25 requisições que também falhariam.
Os objetos dessa página são registrados como **não coletados** e aparecem no
relatório — nunca são omitidos em silêncio.

### Coleta parcial nunca se passa por completa

Todo snapshot registra o escopo (`meta.scope`) e a saúde da coleta
(`meta.collection`). O relatório mostra os dois no topo:

```
✓ Escopo da coleta : 1 grupo(s) de hosts: Vibe Tecnologia
✓ Hosts no escopo  : 36
⚠ Coleta parcial por escopo: cobre apenas o que está listado acima, não o ambiente inteiro.
...
── Coleta ─────────────────────────────────────────────────────
  duração                       : 47.2s
  tamanho de página             : 250
  páginas hidratadas            : 23
  retries por erro transitório  : 2
  lotes reduzidos pelo servidor : 1
    ↓ trigger.get: 250 → 125
```

`complete_environment` só é verdadeiro quando a coleta varreu o ambiente inteiro
**e** nada ficou para trás.

### Interrupção e retomada

Se a coleta morre no meio, o que já veio é gravado num diretório `..._parcial/`
com `collection.partial: true`. Ele **não** é uma base válida — serve para
auditoria e para retomar. Os snapshots anteriores ficam intactos, porque cada
coleta escreve num diretório novo.

```bash
python main.py collect --host-group "Vibe Tecnologia" --resume
```

`--resume` reaproveita os IDs já descobertos pela última coleta do **mesmo
escopo**, pulando a fase de descoberta. Ele soma esses IDs aos que a descoberta
atual encontrar — retomar nunca esconde objetos novos, e um trigger apagado no
Zabbix simplesmente não volta na hidratação.

### Consolidação (`merge`)

```
Vibe Tecnologia (segunda) ─┐
Zabbix servers  (terça)   ─┼─► merge ─► base consolidada
Ativos de Rede  (quarta)  ─┘
```

O merge acontece no **snapshot bruto**, e a normalização é refeita sobre o
resultado. Isso não é detalhe de implementação: colisões de `alert_key`, famílias
e regras multi-host só existem quando se olha o conjunto todo. Juntar
`alerts.json` já prontos esconderia exatamente o que a base precisa mostrar.

A deduplicação é por ID natural (`triggerid`, `hostid`, `itemid`, `groupid`,
`templateid`) — o mesmo objeto em dois snapshots vira **uma** entrada. Quando as
duas versões divergem, vence a coleta mais recente e a divergência é registrada
como conflito no relatório. Estado de runtime (`value`, `state`) fica fora da
comparação: `OK`/`PROBLEM` muda o tempo todo e não é mudança de configuração.

Um merge de grupos **não** é declarado ambiente inteiro, e uma fonte parcial
torna a base consolidada parcial.

---

## 14. Alerta, família, procedimento

São três coisas diferentes e o modelo não as confunde:

| Conceito | O que é | Onde vive |
|---|---|---|
| **Alert** | um trigger concreto do Zabbix | `alerts.json`, uma entrada por trigger |
| **Alert family** | a regra que gera N alertas (protótipo de LLD, trigger replicado) | `family_key`, uma ficha por família |
| **Procedure** | o que se faz quando o alerta toca | bloco `operational` da ficha |

Uma `alert_key` **não** é um procedimento. Uma família pode ter dezenas de
alertas com um procedimento só; um mesmo procedimento pode servir a várias
famílias. Por isso a coleta gera ficha de **família**, e o `override` existe para
quando uma pessoa decide que um caso específico foge da regra.

### O procedimento é o bloco `operational`

Os campos pedidos pela Fase 2 (título, objetivo, sintomas, causa provável,
verificações, ações, validação, escalonamento, riscos, observações) vivem em
`operational` — não numa entidade `Procedure` paralela. Criar uma segunda
entidade duplicaria a máquina de estados, o hash de revisão e o controle de
concorrência, e abriria a porta para as duas divergirem.

`procedure_status` é derivado de `doc_status` e gravado na ficha:

```
doc_status                  procedure_status
──────────────────────────────────────────────
undocumented            ->  missing
pending_review          ->  draft
documented / reviewed   ->  documented
review_needed           ->  needs_review
not_applicable          ->  not_applicable
```

**Nenhum procedimento é inventado.** Enquanto ninguém escrever, o estado é
`missing`. A coleta nunca escreve em `operational`, e a IA também não.

### As três camadas nunca se misturam

```
zabbix          FATO OBSERVADO   "Filesystem / está com 8% livre"    (vem do Zabbix)
ai_suggestion   SUGESTÃO         "verificar arquivos grandes e logs" (a IA propõe)
operational     VERDADE HUMANA   "procedimento oficial"              (uma pessoa aprova)
```

Uma sugestão pode ser copiada para `operational` por uma pessoa, mas a aprovação
continua humana. Sugestão nunca conta como procedimento.

---

## 15. Critério de conclusão da Fase 2

| # | Critério | Onde verificar |
|---|---|---|
| 1 | coleta de ambientes grandes sem requisição gigante | `test_scale.py::test_nenhuma_requisicao_pede_o_ambiente_inteiro_de_uma_vez` |
| 2 | triggers paginados | `test_scale.py::TestPaginacao` |
| 3 | host group individual | `python main.py collect --host-group "..."` |
| 4 | múltiplos host groups | `--host-group` repetido ou com vírgulas |
| 5 | retry em HTTP 500/502/503/504 | `test_scale.py::TestRetry` |
| 6 | coletas armazenadas separadamente | `test_merge.py::TestSnapshotsIndependentes` |
| 7 | snapshots consolidáveis | `python main.py merge` |
| 8 | merge sem duplicação | `test_merge.py::test_nao_duplica_triggers_hosts_nem_itens` |
| 9 | progresso visível | `src/progress.py`, saída do `collect` |
| 10 | parcial x global distinguidos | `meta.scope.complete_environment` + topo do relatório |
| 11 | templates opcionais | comportamento da ETAPA 1, preservado |
| 12 | alert_key e famílias | `normalize.py`, preservado |
| 13 | colisões detectadas | `collisions.json`, preservado |
| 14 | Procedure sem inventar | `operational` + `procedure_status: missing` |
| 15 | 3 camadas separadas | `zabbix` / `ai_suggestion` / `operational` |
| 16 | testes da Fase 1 passando | 99 testes originais, todos verdes |
| 17 | testes novos de escala | `test_scale.py`, `test_merge.py`, `test_cli_fase2.py` |
| 18 | nenhuma escrita no Zabbix | `test_readonly.py` + `test_cli_fase2.py::TestReadOnlyPreservado` |

---

## 16. Interface web (Fase 3)

```bash
python main.py collect     # 1. coletar
python main.py serve       # 2. abrir http://127.0.0.1:8000
```

Uma interface local para navegar os ~19.000 alertas sem abrir JSON nem rodar
comando. Ela lê o snapshot mais recente que **não** seja parcial; `--snapshot`
escolhe outro, e a página **Status da coleta** lista os disponíveis.

### Stack: biblioteca padrão, e o motivo

`http.server` da stdlib + HTML/CSS/JS sem build. O projeto tem **uma**
dependência externa (`requests`) e isto é uma ferramenta local, de um operador
por vez, servindo um arquivo em disco: não há multi-tenancy, autenticação nem
concorrência. Um framework traria dependências, versionamento e um passo de
build sem resolver nenhum problema que exista aqui.

Medido com 18.903 alertas sintéticos (`alerts.json` de 31 MB):

| | |
|---|---|
| carga inicial do modelo | 2,7 s, uma vez |
| memória do processo | ~290 MB |
| `GET /api/dashboard` | 68 ms |
| `GET /api/alerts` (qualquer página) | 45 ms |
| `GET /api/alerts?q=certificado` | 18 ms |
| `GET /api/search?q=api` | 7 ms |

A tabela nunca recebe a lista inteira: filtro, ordenação e paginação acontecem
no servidor e cada página traz no máximo algumas dezenas de linhas.

### Ela não fala com o Zabbix

O processo do `serve` **não importa o cliente do Zabbix, não lê o token e não
abre conexão com a API**. A garantia é estrutural, não uma promessa — um teste
verifica os imports de `src/web/` por AST e falha se algum deles aparecer.

A única escrita do sistema é `POST /api/procedures/<família>`, que grava em
`docs/alerts/`. Nunca no Zabbix.

Outras travas: escuta só em `127.0.0.1` por padrão (`--host` avisa o que muda),
`PUT`/`DELETE` respondem 405, `POST` só existe na rota de procedimentos, e os
arquivos estáticos são resolvidos com o caminho normalizado — `..` não escapa.

### Endpoints

Todos são somente leitura, exceto o `POST` indicado.

```
GET  /api/dashboard              cards, severidades, qualidade, top famílias
GET  /api/alerts                 lista paginada — busca e filtros
GET  /api/alerts/<triggerid>     detalhe completo do alerta
GET  /api/families               famílias, ordenadas por quantidade de alertas
GET  /api/families/<id>          alertas, hosts, expressões, itens, tags
GET  /api/hosts                  lista de hosts
GET  /api/hosts/<hostid>         famílias, alertas, itens, dependências
GET  /api/host-groups            grupos com hosts, alertas e severidades
GET  /api/host-groups/<slug>     hosts, famílias e alertas do grupo
GET  /api/procedures             famílias por estado do procedimento
POST /api/procedures/<família>   grava o procedimento LOCAL  ← única escrita
GET  /api/collisions             colisões com os triggers envolvidos
GET  /api/status                 snapshot em uso, execução da coleta, redação
GET  /api/search?q=              busca global agrupada por tipo
```

Filtros de `/api/alerts`: `q`, `host`, `host_group`, `family`, `severity`,
`procedure`, `discovered`, `comment`, `tags`, `dependencies`, `collision`,
`sort`, `order`, `page`, `per_page`.

Os filtros também vivem na URL da interface (`/alerts?q=vpn&severity=Disaster`),
de propósito: no NOC uma consulta útil é colada no chamado e precisa abrir igual
do outro lado.

### O que ela não reinventa

A interface **não** define um segundo modelo de dados. A família de um alerta é
`core.models.build_family_key(alert)` — a mesma função que o `reconcile` usa
para nomear a ficha. É isso que faz o link família → procedimento ser exato: se
a regra mudar em `core/models.py`, a interface acompanha sozinha, e um teste
trava essa igualdade.

### Estados ausentes não são erros

Templates invisíveis, alerta sem comentário, sem tags, sem dependência, sem
procedimento: todos são estados válidos e aparecem como *"não disponível"* ou
*"não resolvido pela coleta"* — nunca como falha da aplicação.

---

## 17. Segredos na configuração do Zabbix

A primeira coleta real trouxe isto numa expressão de trigger:

```
avg(/Saq - AWS/aws_check.py[--access-key, "AKIA…", --secret-key, "…"], 5m) >= 5
```

Uma credencial de produção, em texto claro, dentro do Zabbix. O Zabbix-Wiki não
criou o problema, mas não pode multiplicá-lo — então a coleta redige o **valor**
antes de gravar:

```
--secret-key, "KwoaLm…"   ->   --secret-key, "[REDACTED:3f7a1c9e]"
```

O nome do parâmetro e a estrutura da expressão ficam. O sufixo é um hash curto
do valor, e isso importa por três motivos:

* dois segredos **diferentes** continuam gerando textos diferentes, então a
  detecção de colisão da Fase 1 segue funcionando;
* o **mesmo** segredo gera sempre o mesmo marcador, então `source_hash` é
  estável e a ficha não cai em `review_needed` a cada coleta;
* redigir duas vezes não muda nada (idempotente), então consolidar snapshots já
  redigidos é seguro.

**Não** são redigidos: macros do Zabbix (`{$PASSWORD}` é referência, não valor)
nem a palavra solta ("Certificate password expires in 30 days" não tem segredo).

A redação roda **antes** da normalização, então `source_hash` e
`expression_signature` já nascem calculados sobre o texto redigido. Fichas
criadas antes desta versão vão acusar `review_needed` uma vez, e depois
estabilizam. `ZABBIX_REDACT_SECRETS=false` ou `--no-redact` desliga (não
recomendado); a página **Status da coleta** mostra em vermelho quando está
desligada, e quantos valores foram redigidos.

**Redigir no snapshot não resolve o problema de origem.** A credencial continua
em texto claro no Zabbix, visível a quem tem leitura na API. Rotacione-a.

---

## 18. Fluxo completo

```
     Zabbix  ──read-only──>  collect  ──>  snapshot (redigido)
                                              │
                                              ├──>  serve   → interface local
                                              └──>  reconcile → docs/alerts/
                                                                    │
                                                        procedimento escrito
                                                          por uma pessoa
```

Do zero até enxergar o ambiente:

```bash
cp .env.example .env && $EDITOR .env
python main.py check       # credenciais ok?
python main.py collect     # ~1 min para 19k triggers
python main.py serve       # http://127.0.0.1:8000
```

### Testes

```bash
python -m unittest discover -s tests -t .
```
