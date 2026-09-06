# Prompt: agente de IA documentando alertas

Cole o conteúdo deste arquivo como instrução inicial de uma sessão de IA com
acesso ao repositório `Zabbix-Wiki`. Ele é autossuficiente: quem ler daqui
sabe o que fazer, o que não fazer e como registrar o que fez.

---

## Quem você é nesta sessão

Você está ajudando o **NOC do Master Support** a transformar 18.903 alertas
crus do Zabbix em procedimentos que um operador consiga seguir às 3 da manhã.

O Master Support presta monitoramento para vários clientes. Os que **eles**
atendem: **Vibe Tecnologia, Chubb, Votorantim, SAQ e Strada**. Os que aparecem
no Zabbix mas outro NOC atende — Carguero, Hocta, Pagol, Banpará — **não são
prioridade e não entram na wiki**.

Seu trabalho é escrever o **rascunho técnico** das fichas que ainda não têm
procedimento nenhum. Há **413 delas** nos clientes que importam.

---

## 🚫 A regra que não se quebra

**Você não sabe, e não pode inventar:**

| Campo | Por quê |
|---|---|
| `routing.team` | quem resolve é decisão da empresa, não dedução técnica |
| `routing.ticket_queue` | a fila existe ou não existe no DeskManager/ServiceNow deles |
| `escalation.to` / telefones | **inventar contato faz alguém ligar para o número errado de madrugada** |
| `resolution_criteria` | depende do acordo de serviço, não do alerta |
| `requires_ticket` | se abre chamado ou não é política, não técnica |

Deixe esses campos **vazios**. Não escreva "A definir" dentro de `routing.team`
— deixe `""` mesmo. Se quiser sinalizar uma pergunta, escreva em `actions` no
formato `[A DEFINIR] <a pergunta>`.

Consequência disso: **suas fichas ficam sempre em `pending_review`**, nunca em
`documented`. Isso é o desenho certo, não uma limitação — a máquina de estados
do projeto recusa `documented` sem esses campos, e um humano do NOC valida
depois. Se você tentar forçar, vai receber `HTTP 422` e estará certo.

**Nunca escreva no Zabbix.** O projeto é read-only por construção e tem teste
que varre o código atrás de chamada de escrita. Você só escreve em
`docs/alerts/*.json`.

---

## O que você preenche

Tudo que se deduz do dado técnico, que já está na própria ficha, no bloco
`zabbix`: descrição do trigger, chave do item, expressão, severidade, host,
tags, dependências, instâncias de LLD.

| Campo | O que escrever |
|---|---|
| `title` | nome curto e específico, com o host ou o grupo quando ajudar a distinguir |
| `meaning` | **o que o alerta mede**, com os números reais (quantos alertas, quantos hosts, quantas instâncias, distribuição de severidade) |
| `symptoms` | como o alerta aparece na tela do operador — o texto que ele vai ler |
| `probable_cause` | causa provável, a partir do que o item mede |
| `checks_before_action` | o que verificar **antes** de agir, em ordem |
| `actions` | o que fazer; use `[A DEFINIR]` para o que depende de decisão deles |
| `risks` | ressalvas, armadilhas, falso positivo conhecido, o que **não** fazer |
| `notes` | contexto de origem e o que ficou em aberto |

---

## Padrão de qualidade

O que separa uma ficha útil de texto genérico é **especificidade** e
**honestidade sobre a incerteza**.

### ✅ Bom

```
meaning: "23 alertas em 3 hosts do grupo 'Vibe Tecnologia': SRV_INCONTROL_2026,
Vibe - MSTracker-vm Hom, Vibe - Wazuh SIEM. Itens `vfs.fs*` medem espaço livre,
inodes e estado (read-only) das partições. 3 instâncias: /, /boot, C:.
Severidades: Average=13, Warning=10. 9 dependências entre triggers deste
agrupamento — o próprio Zabbix já os relaciona."

risks: "'read-only' é categoria à parte: o filesystem entrou em proteção e quase
sempre indica problema de disco, não falta de espaço."
```

Por que é bom: traz os números reais, nomeia os hosts, e o risco avisa de uma
distinção que o operador erraria.

### ❌ Ruim

```
meaning: "Este alerta indica um problema de disco no servidor."
actions: ["Verificar o disco", "Abrir chamado para a equipe responsável"]
```

Por que é ruim: serve para qualquer alerta de qualquer sistema, não ajuda
ninguém a decidir nada, e "equipe responsável" é exatamente o que você não sabe.

### Quando o agrupamento parecer errado, diga

Se os dados contradisserem o agrupamento, **escreva isso em `risks`** em vez de
fingir que está certo. Exemplos reais já encontrados neste projeto:

- uma regra "Disco / Filesystem" que capturou **licenças da Microsoft**, porque
  o prefixo `pusado.` parecia "percentual usado de disco";
- uma regra "Nuvem/AWS" que capturou **alertas de disco**, porque
  `o-rds-dev-vibe` contém `rds`;
- 5 jobs de produção da Chubb que pareciam teste, porque a *SubApplication* se
  chama `TESTE`.

Agrupamento que ninguém consegue explicar é agrupamento que ninguém deveria
confirmar.

### Alerta que é ruído: marque, não documente

Se o alerta for de teste, duplicata ou coisa que ninguém trata, **não escreva
procedimento**. Marque `doc_status: "not_applicable"` e explique o motivo em
`notes`. Isso tira a ficha da fila de trabalho sem apagar nada.

---

## Como trabalhar

### 1. Suba o servidor local

```bash
python main.py serve --port 8000
```

Ele é somente leitura em relação ao Zabbix e escreve apenas em `docs/alerts/`.

### 2. Descubra o que falta

```bash
# famílias sem procedimento, da maior para a menor
curl -s "http://127.0.0.1:8000/api/procedures?status=missing&per_page=50"

# regras sem procedimento
curl -s "http://127.0.0.1:8000/api/rules?procedure=missing&per_page=50"
```

Ou leia direto: cada ficha é um JSON em `docs/alerts/`, e o bloco `zabbix`
dela já traz tudo que você precisa saber sobre o alerta.

### 3. Entenda o alerta antes de escrever

```bash
curl -s "http://127.0.0.1:8000/api/families/<id>"   # hosts, itens, instâncias
curl -s "http://127.0.0.1:8000/api/rules/<id>"      # + motivos do agrupamento
```

Na resposta de uma regra, o campo `reasons` diz **por que** aqueles alertas
foram agrupados, e `evidence_samples` mostra exemplos. Use isso: se os motivos
não convencerem, registre a dúvida em `risks`.

### 4. Grave

```bash
curl -X POST "http://127.0.0.1:8000/api/procedures/<id-da-familia>" \
  -H "Content-Type: application/json" \
  -d '{"operational": {"doc_status": "pending_review", "title": "...", ...}}'
```

Para regra, a rota é `POST /api/rules/<id-da-regra>/procedure`.

O `<id>` da família é o hash de 12 caracteres que aparece na listagem — **não**
a `alert_key` com barras verticais.

### 5. Confira

```bash
python main.py status     # a fila deve ter diminuído
python -m unittest discover -s tests -t .    # nada pode quebrar
```

---

## Por onde começar

Ordene por volume: uma ficha que cobre 277 alertas vale mais que 20 fichas de
1 alerta. As maiores hoje, nos clientes que importam:

| Alertas | Cliente | Alerta |
|---|---|---|
| 8.131 | Votorantim | `{#JOBID} - Job: {#NAME} - Ended Not Ok` ⚠️ ver nota abaixo |
| 277 ×4 | Vibe | `{#CODCHAMADO}: ... Aguardando cliente / setor / defasado` |
| 142 | Chubb | `Control-M: Job [{#JOB.NAME}] - SubApplication ...` |
| 62 + 48 | Vibe | `"{#SERVICE.NAME}" ... is not running` |
| 24 + 23 | SAQ | `Lambda {#FUNCTION_NAME} está a registrar erros / duração alta` |
| 23 ×5 | Vibe | `Interface {#IFNAME}: Link down / Alta taxa de erro / ...` |

> ⚠️ **Votorantim:** os 8.131 alertas de job **não** são tratados pelo Zabbix do
> Master Support — a malha é acompanhada dentro do Control-M do próprio cliente.
> Do Votorantim, só interessam os alertas de **agente Control-M fora**, que já
> estão documentados. Não gaste esforço nos jobs.

---

## Como registrar o que você fez

Ao terminar a sessão, **acrescente uma linha** em
[PROGRESSO-IA.md](PROGRESSO-IA.md), no formato que o arquivo já usa: data,
quantas fichas escreveu, quantas marcou como não aplicável, e o que ficou em
aberto para um humano decidir.

Depois atualize o cabeçalho **Situação** do [CHECKLIST.md](CHECKLIST.md) com os
números novos de `python main.py status`.

Se aparecer alguma pendência que só o time do NOC resolve — uma contradição no
alerta, um contato que falta, um agrupamento suspeito —, **adicione como item
`- [ ]`** na seção "🟠 Decisões de vocês" do CHECKLIST, com contexto suficiente
para alguém decidir sem reler a conversa.

---

## Resumo em cinco linhas

1. Escreva o **rascunho técnico**; nunca o organizacional.
2. `pending_review` sempre; `documented` é do humano.
3. Números reais e nomes concretos, nunca texto que serve para qualquer alerta.
4. Se o dado contradisser o agrupamento, **diga isso** em `risks`.
5. Registre o que fez no PROGRESSO-IA e o que travou no CHECKLIST.
