"""Camada de análise: da família técnica à regra operacional.

    TechnicalFamily  →  RuleCandidate  →  ConfirmedOperationalRule
                                              ↓
                                          Instance  →  Alert

A família técnica (Fase 1) continua existindo e não é substituída: ela é a
evidência de origem. Esta camada olha para os alertas e **sugere** unidades
operacionais — agrupamentos que provavelmente merecem um procedimento só.

Nada aqui decide sozinho. Todo candidato carrega confiança e motivos, e só vira
regra confirmada quando uma pessoa confirma.
"""
