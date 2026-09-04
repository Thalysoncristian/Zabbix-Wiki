# Base de Conhecimento Operacional de Alertas Zabbix

Transformar os alertas do Zabbix em uma base de conhecimento que responda, às 03h17
da madrugada, o que o operador precisa saber: *o que é esse alerta, o que verificar,
espero ou ajo, abro chamado, para qual fila, quem é o responsável agora, qual o SLA,
quando escalar e como sei que resolveu.*

O desenvolvimento é **incremental**. Este repositório está na **ETAPA 1**.

```
>> ETAPA 1  coletar os alertas reais do Zabbix e validar os dados   <<  VOCÊ ESTÁ AQUI
   ETAPA 2  normalizar + modelo operacional completo
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
`ZABBIX_HOST_GROUPS`, `OUTPUT_DIR`.

---

## 4. Uso

```bash
# testa conexão e credenciais, sem coletar nada
python main.py check

# coleta completa
python main.py collect

# coleta reduzida, para a primeira validação
python main.py collect --limit 50 --examples 3

# apenas alguns grupos de hosts
python main.py collect --host-group "Infraestrutura" --host-group "SIEM"

# apenas triggers habilitados em hosts monitorados
python main.py collect --only-monitored
```

Opções de `collect`: `--limit`, `--host-group` (repetível), `--only-monitored`,
`--include-template-triggers`, `--examples N`, `--output DIR`.
Opções globais (antes do subcomando): `--env-file ARQUIVO`, `-v/--verbose` —
ex.: `python main.py --env-file .env.homolog collect`.

Por padrão são coletados os triggers **dos hosts** (`templated=false`) — que é o que
gera alerta de verdade. O trigger do template é alcançado pela cadeia `templateid`
para servir de escopo da chave.

Na coleta completa (sem `--limit`), o `trigger.get` é **paginado em lotes de
hosts** (`ZABBIX_TRIGGER_BATCH_SIZE`, padrão 50). Pedir os triggers de milhares
de hosts numa única chamada faz o servidor Zabbix estourar tempo/memória e
responder `HTTP 500` com corpo vazio. O progresso de cada lote é impresso
durante a coleta.

### Saída esperada

```
✓ Conectado ao Zabbix (API 7.0.0, api_token (Authorization: Bearer))
✓ 412 triggers encontrados
✓ 37 hosts resolvidos
✓ 9 host groups resolvidos
✓ 14 templates resolvidos
✓ 388 itens relacionados resolvidos
✓ Snapshot bruto salvo -> output/snapshots/20260903_031705/raw/zabbix_raw.json
✓ Alertas normalizados salvos -> output/snapshots/20260903_031705/normalized/alerts.json
✓ 96 alertas únicos
✓ 2 possíveis colisões de alert_key
```

Seguido de um detalhamento (severidades, estratégias de chave, chaves
compartilhadas, colisões) e de exemplos completos dos JSONs gerados.

---

## 5. Estrutura da saída

```
output/
└── snapshots/
    ├── latest -> 20260903_031705
    └── 20260903_031705/
        ├── raw/
        │   └── zabbix_raw.json      # exatamente o que a API devolveu + log das chamadas
        ├── normalized/
        │   ├── alerts.json          # alertas autocontidos (1 por trigger)
        │   ├── alert_keys.json      # agrupamento por alert_key
        │   └── collisions.json      # colisões detectadas, com detalhes
        └── report.json              # relatório completo da coleta
```

Snapshots **nunca são sobrescritos** — se dois rodarem no mesmo segundo, o segundo
recebe sufixo (`..._2`). Isso permite auditoria e comparação histórica.

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
├── main.py                    # python main.py collect | check
├── .env.example
├── requirements.txt
├── src/
│   ├── config.py              # .env -> Settings (parser próprio, sem dependências)
│   ├── zabbix_client.py       # JSON-RPC read-only + allowlist + auth por versão
│   ├── collect.py             # orquestra a coleta e resolve os relacionamentos
│   ├── normalize.py           # snapshot bruto -> alertas autocontidos
│   ├── keys.py                # alert_key, normalização, source_hash
│   ├── snapshot.py            # escrita imutável em output/snapshots/
│   ├── report.py              # relatório da coleta
│   └── cli.py
└── tests/
    ├── fixtures/fake_zabbix.py  # Zabbix falso (transporte em memória)
    ├── test_keys.py
    ├── test_readonly.py
    ├── test_normalize.py
    ├── test_pipeline.py
    └── test_cli.py
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
| `HTTP 500` com corpo vazio | o servidor Zabbix estourou tempo/memória montando a resposta. A coleta completa já pagina o `trigger.get` em lotes de hosts; se ainda ocorrer, reduza `ZABBIX_TRIGGER_BATCH_SIZE` (ex.: 20 ou 10) e/ou aumente `ZABBIX_TIMEOUT` |
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
