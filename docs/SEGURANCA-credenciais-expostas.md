# Credenciais em texto claro na configuração do Zabbix

**Achado em:** 2026-09-06, durante a documentação da Fase 2
**Status:** aguardando rotação pelo time responsável
**Este documento não contém os valores.** Eles estão no Zabbix e nos snapshots
locais em `output/` (que é ignorado pelo git).

## O que foi encontrado

Credenciais de produção gravadas em texto claro **dentro da expressão de
trigger / chave de item** no Zabbix. Qualquer pessoa ou integração com
permissão de leitura na API enxerga esses valores.

| Host | Item | Tipo de credencial | Triggers afetados |
|---|---|---|---|
| Saq - AWS | `aws_check.py` | `--access-key` + `--secret-key` da AWS (região sa-east-1) | 57 |
| Saq - Pix | `check_pix_api.py` | `--clientsecret` + `--hmacsecret` | 3 |
| Saq - Pix | `check_pix_api_detalhes.py` | `--clientsecret` + `--hmacsecret` | 2 |

Outros hosts do mesmo ambiente usam **macro** no lugar do valor
(`--access-key, "{$AWS.ACCESS.KEY}"`), que é a forma correta — o problema está
restrito aos itens acima.

## O que já foi feito

- As fichas em `docs/alerts/` foram redigidas: onde havia o valor, agora há
  `[REDACTED:<hash>]`. São 13 fichas, 54 valores.
- Verificado que **nenhuma credencial entrou no histórico do git**. A chave
  `AKIAIOSFODNN7EXAMPLE` que aparece em `tests/test_redact.py` é a chave de
  exemplo pública da AWS, usada de propósito nos testes.
- `output/` está no `.gitignore`, então os snapshots nunca foram versionados.
- Dois furos na redação foram corrigidos (ver abaixo).

## O que ISSO NÃO resolve

**Redigir arquivo local não desfaz a exposição.** A credencial continua em
texto claro no Zabbix. As ações que resolvem são do time:

1. **Rotacionar** as credenciais (AWS e PIX). Enquanto não forem rotacionadas,
   valem como comprometidas — não há como saber quem já as leu.
2. Substituir o valor por **macro** no item do Zabbix
   (`{$AWS.SECRET.KEY}`), como os outros hosts já fazem. Zabbix 7.x suporta
   macro do tipo *Secret text*, que não é exibida depois de salva.
3. Revisar quem tem permissão de leitura na API do Zabbix.

## Por que o monitoramento não pegou isso sozinho

Duas causas distintas, ambas tratadas:

**1. Cronologia (não era bug).** O snapshot `20260905_181510` foi coletado às
21:15 UTC; `src/redact.py` foi commitado às 21:51 UTC — 36 minutos depois. O
snapshot nasceu de uma versão do coletor que ainda não redigia, e as fichas
herdaram o texto cru pelo `reconcile`. Uma coleta nova já teria redigido a
parte da AWS.

**2. Dois furos reais na redação** (corrigidos em `src/redact.py`, com teste):

- O separador vírgula não era aceito no par **sem aspas**:
  `--clientsecret, "valor"` era redigido, `--clientsecret,valor` não. Como
  chave de item do Zabbix separa parâmetro por vírgula, era justamente a forma
  mais comum de o segredo aparecer.
- `secret` sozinho nunca casava dentro de `hmacsecret`: o padrão exige começo
  de palavra, e antes de `secret` vinha `hmac`. Agora qualquer parâmetro
  terminado em "secret" conta.

Estes dois valiam para coletas novas também — não eram só um problema do
snapshot antigo.

## Como conferir se voltou

```bash
grep -rlE "AKIA[0-9A-Z]{16}|(secret|password|token)[\"' ]*[:=,][\"' ]*[A-Za-z0-9/+._-]{12,}" docs/
```

Sem saída = limpo. Depois de rotacionar e trocar por macro no Zabbix, uma
coleta nova (`python main.py collect`) deve trazer a macro, não o valor.
