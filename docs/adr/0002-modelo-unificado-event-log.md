# ADR 0002 — Modelo unificado event-log para a camada raw

**Data:** 2026-05-26 (reescrito após análise empírica do snapshot 13-05)
**Estado:** Aceite
**Relaciona-se com:** [ADR 0001](0001-bd-acumuladora-de-snapshots.md), [ADR 0003](0003-estrategia-de-leitura-historica.md), [ADR 0004](0004-baseline-e-cobertura-temporal.md)

## Contexto

O ADR 0001 estabelece que a BD acumula snapshots. Uma primeira hipótese assumia que pagamentos eram fundamentalmente diferentes de presenças — pagamentos mutáveis (anulação retroativa muda a linha original) versus presenças append-only. Sob essa hipótese, o desenho seria "dois regimes" (state-tracking versus event-log).

A análise empírica do snapshot atual de pagamentos (96.771 linhas, 11+ anos de histórico) refutou parcialmente esse pressuposto:

- A chave única por linha **não** é `pag_no_pag` (37k únicos para 96k linhas — cada pagamento gera N parcelas). É **`no_parcela`** (94.867 únicos de 96.771; resíduo de 1.904 duplicados a investigar como qualidade de dados).
- O software de gestão, quando anula um pagamento, **atualiza a linha original** (`pag_anulado: Não → Sim`, preenche `pag_data_anulacao`). Não cria linha nova de nota de crédito (só 1 valor negativo em 96k linhas).
- As anulações concentram-se nos primeiros dias após o pagamento: **mediana 7 dias**, **99% em ≤90 dias**, **100% em ≤365 dias**. Linhas com mais de 1 ano de idade estão congeladas com certeza estatística total neste histórico.

Em consequência: pagamentos *são* mutáveis, mas dentro de uma janela curta e previsível. Não justificam um regime conceptualmente separado.

## Decisão

Adoptar um **modelo unificado event-log** para toda a camada raw. Cada tabela `_raw_*` é um log de eventos identificados por uma chave natural única, com regra de ingestão escolhida pela mutabilidade da fonte.

### `_raw_pagamentos`

- **Chave primária:** `no_parcela`.
- **Regime de ingestão: UPSERT.** Cada upload compara cada linha por `no_parcela`:
  - Novo `no_parcela` → INSERT.
  - `no_parcela` existente com diferenças em campos mutáveis (`pag_anulado`, `pag_data_anulacao`, `parcelas_valor_liquido`) → UPDATE.
  - `no_parcela` existente sem diferenças → IGNORE.
- **Não há `snapshot_data` na chave.** Há uma coluna `atualizado_em_snapshot` (timestamp do snapshot que tocou a linha pela última vez), útil para debug e auditoria. Não participa em queries de KPI.

#### Campos de dimensão utente (revisão 2026-07-31)

As colunas `utente_status`, `utente_gestor`, `utente_tipo_socio`, `doc_nome` e `utente_data_insc` não descrevem o evento pagamento — são a **dimensão utente**, que o export desnormaliza em todas as linhas da sócia, sempre com o estado *atual*. Tratamento no UPSERT:

- **Seguem sempre o snapshot mais recente** (entram na comparação e no UPDATE). Sem isto, a definição "sócia ativa no snapshot" (`utente_status == 'A'`) apodrecia silenciosamente: uma sócia que cancelasse ficava `A` para sempre nas linhas antigas, porque deixa de gerar linhas novas.
- **Sem registo em `_log_alteracoes`.** Uma mudança de status toca em massa todas as linhas históricas da sócia a cada export — não é anomalia a investigar. O log fica reservado às mutações do evento (anulações, valor).

### `_raw_presencas`

- **Chave primária:** `(utente_no_insc, data, hora_entrada)`.
- **Regime de ingestão: INSERT OR IGNORE.** Eventos imutáveis: aparece uma vez, fica. Repetições silenciosas.
- **Coluna `ingerido_em_snapshot`** para rastrear o primeiro snapshot que trouxe o evento.

### `_log_alteracoes` (opcional, ligado por defeito para pagamentos)

Quando uma linha de `_raw_pagamentos` é atualizada, regista-se uma linha em `_log_alteracoes`:

| Coluna | Notas |
|---|---|
| `no_parcela` | chave da linha alterada |
| `snapshot_data` | snapshot que causou a alteração |
| `campo` | nome do campo mutado |
| `valor_antigo` | valor antes |
| `valor_novo` | valor depois |
| `detectado_em` | timestamp wall-clock |

Volume previsto: ~350 alterações/ano (3.5% das ~10k novas linhas/ano que ainda estão na janela de mutabilidade). Insignificante em SQLite. Não é consultado em KPIs — só em auditoria pontual ("este pagamento foi anulado em que snapshot?").

## Consequências

**Ganhos:**
- **Schema simétrico e simples.** Uma só ideia (event-log com chave natural), duas variantes operacionais (UPSERT vs IGNORE) escolhidas pela mutabilidade da fonte.
- **Tabela de pagamentos compacta.** Uma linha por `no_parcela`, em vez de N × snapshots. Para os 96k pagamentos atuais + ~15k/ano de delta, a tabela cresce ~110k → ~170k em 4 anos. Confortável.
- **Queries de KPI triviais.** "MRR de Maio" é uma agregação direta sobre `_raw_pagamentos` filtrada por `parcelas_disponivel ∈ Maio` e `pag_anulado="Não"`. Sem escolha de snapshot, sem vistas duplicadas.
- **Auditoria preservada.** O `_log_alteracoes` responde a "quando foi anulado?" quando alguém quiser, sem peso em queries normais.

**Custos:**
- **Perdemos a verdade temporal "snapshot por snapshot" para pagamentos.** Se um pagamento foi anulado em Junho, a tabela mostra só "anulado" daí em diante. Para o caso 99% (anulações em <=90 dias, dentro do mês ou mês seguinte), isto não muda nada. Para o caso 1% (anulações em 90-365 dias), o KPI histórico vai mexer ligeiramente quando a anulação entrar — mas isso é informação útil, não bug.
- **`_log_alteracoes` ocupa mais lugar conceptual do que linhas.** É uma tabela barata que vale a pena ter desde o dia 1; quem nunca a consultar nem sabe que existe.

## Implicações para o ADR 0003

A escolha original de "regra β" (primeiro snapshot pós-fecho de mês) deixa de fazer sentido — não há "snapshots por mês" a consultar para pagamentos, há uma só tabela viva. O ADR 0003 foi reescrito em consequência.

## Como decidir o regime para uma fonte futura

1. Existe chave natural única por linha? Se não, criar uma sintética estável (ex: hash determinístico das colunas-chave) ou recusar a fonte até o produtor a expor.
2. A fonte pode reescrever uma linha já entregue?
   - **Não, nunca** → INSERT OR IGNORE. Imutável.
   - **Sim, dentro de uma janela curta e previsível** → UPSERT + `_log_alteracoes`. É o caso dos pagamentos.
   - **Sim, sem limite temporal claro** → UPSERT, com cuidado adicional: avaliar se vale a pena reabrir a hipótese de "snapshot por linha". Não temos hoje fontes nesta categoria.

## Histórico de revisões

- 2026-07-31: campos de dimensão utente passam a ser comparados e atualizados pelo UPSERT, sem log. Antes só os 3 campos de evento eram comparados — `utente_status` ficava congelado no valor do primeiro snapshot que trouxe a linha, corrompendo a definição "sócia ativa no snapshot" a partir da segunda ingestão.
- 2026-05-26 (inicial): "dois regimes" — state-tracking para pagamentos, event-log para presenças. Baseado no pressuposto de que pagamentos eram mutáveis "a qualquer momento".
- 2026-05-26 (revisão): unificado em event-log, depois de inspeção empírica mostrar que pagamentos são mutáveis apenas numa janela de ≤365 dias, e que a chave natural por linha é `no_parcela`, não `pag_no_pag`.

## Alternativas rejeitadas

- **Modelo único state-tracking (chave composta com `snapshot_data`)**: multiplica a tabela por N snapshots sem ganho real — anulações tardias são raras e capturáveis com UPSERT + log.
- **Modelo único event-log estrito (INSERT OR IGNORE para pagamentos)**: ignora alterações de `pag_anulado` retroativas — falha em casos reais embora raros.
- **State-tracking com janela móvel** (variante α discutida em conversa de 2026-05-26): preserva versões dentro da janela de 18 meses, congela fora. Defensável mas complexa para um benefício pequeno — a diferença entre "MRR de Março visto a 13-Mai" e "MRR de Março visto hoje" é <3% no caso típico.
