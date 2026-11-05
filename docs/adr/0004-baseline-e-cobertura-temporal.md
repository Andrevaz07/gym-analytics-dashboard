# ADR 0004 — Baseline temporal e cobertura explícita dos snapshots

**Data:** 2026-05-26
**Estado:** Aceite
**Relaciona-se com:** [ADR 0001](0001-bd-acumuladora-de-snapshots.md), [ADR 0002](0002-modelo-unificado-event-log.md), [ADR 0003](0003-estrategia-de-leitura-historica.md)

## Contexto

O software de gestão permite que a equipa do ginásio defina uma **janela de datas** ao exportar tanto pagamentos como presenças. Isso introduz risco:

- **Para presenças** (regime INSERT OR IGNORE, ADR 0002): se duas extrações consecutivas têm um gap temporal entre elas (ex: a primeira até 13-Mai, a segunda começando a 20-Mai), perdem-se 14-19 Mai. Como o sistema é append-only, não há "saber depois" que tinha um gap — fica silenciosamente em falta.
- **Para pagamentos** (regime UPSERT, ADR 0002): cada upload tem de cobrir a **janela de mutabilidade** (≤365 dias) para que o UPSERT detete anulações retroativas. Se a gerente extrai só "este mês", as anulações em pagamentos mais antigos ficam invisíveis.

A análise empírica do snapshot atual (2026-05-13) mostra: foi extraído **com janela** (não cumulativo). Para presenças, "este ano" (Jan-Mai 2026). Para pagamentos, janela ainda não confirmada — assume-se que cobre o histórico inteiro porque o snapshot tem linhas desde 2011.

## Decisão

### Cobertura explícita em `_raw_snapshots`

A tabela de metadados `_raw_snapshots` regista, para cada upload:

| Coluna | Pagamentos | Presenças |
|---|---|---|
| `cobertura_de` | `MIN(pag_data)` do ficheiro | `MIN(data)` do ficheiro |
| `cobertura_ate` | `MAX(pag_data)` do ficheiro | `MAX(data)` do ficheiro |
| `gaps_conhecidos` | usado se a janela violar a baseline | usado se houver gap entre uploads |

Estas colunas são populadas automaticamente pela função de ingestão; a gerente nunca as edita.

### Baseline temporal: regras de extracção por fonte

**Pagamentos — baseline fixa:** a gerente extrai sempre com janela `[<baseline>, hoje]`. A baseline é decidida uma vez e fica congelada. Para o primeiro upload, recomenda-se **sem filtro de data** (cumulativo desde o início), o que congela a baseline automaticamente como `MIN(pag_data) ≈ 2011`. O dashboard mostra:

> **Próxima extração de pagamentos**
> No software de gestão:
>   • Data de Início: **deixe em branco** (sem filtro)
>   • Data de Fim: hoje

Justificação para "sem filtro" em vez de baseline mais recente: a tabela `_raw_pagamentos` (ADR 0002) é uma só tabela com UPSERT. Pagamentos antigos não causam problema de volume (UPSERT em chave existente sem mudanças = IGNORE silencioso, custo de I/O em SQLite). Operacionalmente é mais simples para a gerente ("nunca filtre data") do que pedir uma baseline específica.

**Presenças — baseline definida na primeira extração + janela móvel daí em diante:**

- Primeiro upload: a baseline temporal é o que a gerente escolher (no caso atual, "Jan 2026" — não interessa histórico anterior).
- Uploads seguintes: o dashboard sugere `[MAX(cobertura_ate) + 1 dia, hoje]`:

> **Próxima extração de presenças**
> No software de gestão:
>   • Data de Início: **14-Mai-2026** (copie este valor)
>   • Data de Fim: hoje

A janela móvel para presenças é segura porque o regime INSERT OR IGNORE absorve overlap silenciosamente (gerente pode pôr uma data de início *anterior* à sugerida sem partir nada — apenas as presenças novas entram).

### Validação no upload

#### Pagamentos

- Sistema lê `MIN(pag_data)` do ficheiro novo.
- Se for **posterior** ao `MIN(cobertura_de)` já registado em qualquer snapshot anterior de pagamentos, em mais que uns dias:
  > ⚠️ Este ficheiro começa em **2026-05-01**, mas snapshots anteriores cobriam desde **2011-11-09**. Anulações em pagamentos anteriores a Maio 2026 não vão ser detetadas.
  >
  > [ Cancelar e re-extrair sem filtro de data ]   [ Carregar mesmo assim ]
- Se aceita "mesmo assim", marca `gaps_conhecidos` com o intervalo descoberto. KPIs mostram aviso permanente.

#### Presenças

- Sistema lê `MIN(data)` do ficheiro novo.
- Calcula `ultima_cobertura = MAX(cobertura_ate)` de presenças.
- Se `MIN(data) > ultima_cobertura + 1 dia`:
  > ⚠️ Gap detetado: a última extração cobriu até **13-Mai**. Este ficheiro começa em **20-Mai**. Os dias **14-19 Mai** não vão ter dados.
  >
  > [ Cancelar e re-extrair desde 14-Mai ]   [ Carregar mesmo assim ]
- Se aceita "mesmo assim", marca `gaps_conhecidos`. KPI "sócias em risco" mostra aviso.

### Para o snapshot atual (13-05)

Tratamento de exceção, executado uma vez:
- **Pagamentos**: o snapshot cobre 2011→2026 — assumimos completo. `cobertura_de = 2011-11-09`, `cobertura_ate = 2026-05-13`, `gaps_conhecidos = NULL`.
- **Presenças**: o snapshot cobre 2026-01→2026-05-13. `cobertura_de = 2026-01-04` (primeira presença observada), `cobertura_ate = 2026-05-13`, `gaps_conhecidos = NULL`. Baseline de presenças fica fixada em 2026-01-04 — não vamos pedir histórico anterior.

## Consequências

**Ganhos:**
- **gerente tem guidance explícito**, dependente da fonte e dependente do que a BD já sabe. Reduz drasticamente a chance de gap silencioso.
- **Sistema sabe a sua própria cobertura.** O dashboard pode responder a "tenho dados de Março 2026?" lendo metadados, em vez de empiricamente "vê se há linhas em Março".
- **Auditoria simples** — `_raw_snapshots` tem a história de o que foi pedido a cada upload.

**Custos:**
- **3 colunas extra em `_raw_snapshots`.** Trivial.
- **Lógica extra na ingestão.** ~30 linhas: calcular cobertura, comparar com cobertura anterior, decidir alerta. Por fonte (pagamentos diferente de presenças, mas só 2 fontes).
- **gerente tem de aceitar uma cerimónia ligeira no upload** (ler a sugestão, copiar a data). Mitigado por o dashboard tornar a sugestão visual e copiável.

## Limitações conhecidas

- **Gaps internos no próprio export.** Se o ficheiro de presenças tem `data` em 14-Mai mas zero linhas a 15-Mai (porque o ginásio estava fechado nesse dia), o sistema não distingue isso de um gap por extração defeituosa. Para os fins do KPI "sócias em risco" isto não é problema material: o ginásio raramente fica fechado um dia inteiro, e mesmo que aconteça, esse dia está dentro da janela `[cobertura_de, cobertura_ate]` — não conta como gap.
- **Primeiro upload de qualquer fonte.** Não há baseline para validar — confiamos no que a gerente entregar e fixamos a baseline aí. Para pagamentos, mostramos um modal de confirmação ("Este é o primeiro snapshot. Confirme que não aplicou filtro de data.").

## Alternativas rejeitadas

- **Validação puramente declarada pela gerente** (ela diz "extraí sem filtro" e confiamos): frágil — engana-se ou clica sem ler. A heurística empírica (comparar `MIN(data)` com snapshot anterior) é mais robusta.
- **Sem baseline em pagamentos, aceita-se qualquer janela**: incompatível com ADR 0002 — UPSERT só deteta anulações dentro da janela atual; fora dela, alterações ficam invisíveis sem aviso.
- **Forçar exatamente a mesma janela em todos os uploads de pagamentos**: rígido — se ela esquecer e clicar "exportar todos" não há problema, mas o sistema rejeitaria. Em vez disso aceitamos qualquer janela que cubra a baseline e maior.
