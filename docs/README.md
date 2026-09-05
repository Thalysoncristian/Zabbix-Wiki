# Fichas operacionais

`docs/alerts/*.json` é a **fonte de verdade** da base de conhecimento — e por
isso é versionado no git. O histórico do repositório vira o histórico da
documentação: quem escreveu o quê, quando, e o que mudou.

Cada arquivo tem três blocos:

* `zabbix` — fato técnico, vindo da coleta. Não edite à mão: o próximo
  `reconcile` sobrescreve.
* `ai_suggestion` — sugestão automática (ETAPA 8). Nunca é autoridade.
* `operational` — o procedimento oficial. **Só humano escreve aqui.**

As fichas são criadas e atualizadas por:

```bash
python main.py collect      # coleta do Zabbix
python main.py reconcile    # aplica a coleta sobre as fichas
python main.py status       # cobertura da documentação
```

O `reconcile` nunca apaga documentação. Quando o fato técnico muda no Zabbix,
a ficha passa a `review_needed` com todo o conteúdo humano intacto.

## Procedimento

O bloco `operational` **é** o procedimento operacional: título, objetivo,
sintomas, causa provável, verificações, ações, validação, escalonamento, riscos
e observações. Não existe uma entidade `Procedure` separada — duas entidades
para a mesma coisa acabariam divergindo.

`procedure_status` é derivado de `doc_status` e gravado na ficha. Enquanto
ninguém escrever nada, ele é `missing`. **Procedimento não se inventa**: nem a
coleta nem a IA escrevem em `operational`. Uma sugestão da IA vive em
`ai_suggestion` e só vira procedimento quando uma pessoa a escreve — e assina.

## Escopo da coleta

Uma coleta filtrada por grupo (`collect --host-group ...`) só enxerga parte do
ambiente. O `reconcile` respeita isso: fichas de grupos fora do escopo daquela
coleta **não** são marcadas como ausentes, porque ninguém foi procurá-las.

Para aplicar várias coletas de uma vez, consolide antes:

```bash
python main.py merge        # gera output/snapshots/<timestamp>__consolidado/
python main.py reconcile    # usa o snapshot mais recente
```
