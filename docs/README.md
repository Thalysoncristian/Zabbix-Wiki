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
