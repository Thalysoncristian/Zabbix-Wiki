"""Interface web local do Zabbix-Wiki (Fase 3).

Uma camada de LEITURA sobre o que a coleta já produziu. Ela não fala com o
Zabbix, não tem credencial, e não é um segundo modelo de dados: consome o
`alerts.json` do snapshot e as fichas de `docs/alerts/` exatamente como o
`reconcile` as escreve.
"""
