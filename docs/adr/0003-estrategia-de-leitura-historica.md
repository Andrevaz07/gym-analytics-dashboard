# ADR 0003 — Estratégia de leitura: vista única "atual" para pagamentos, leitura direta para presenças

**Data:** 2026-05-26 (reescrito após decisão de modelo unificado event-log)
**Estado:** Aceite
**Relaciona-se com:** [ADR 0001](0001-bd-acumuladora-de-snapshots.md), [ADR 0002](0002-modelo-unificado-event-log.md), [ADR 0004](0004-baseline-e-cobertura-temporal.md)

## Contexto

Uma versão anterior deste ADR propunha duas estratégias para pagamentos: "regra β" (primeiro snapshot pós-fim-do-mês — verdade congelada) e "regra α" (último snapshot — verdade atualizada). A escolha entre as duas dependia de assumir que cada snapshot guardava versões separadas de cada pagamento.

O ADR 0002 (revisto) eliminou essa premissa. Pagamentos passam a viver numa **única tabela** com UPSERT por `no_parcela`. Não há "snapshot 1 vs snapshot 2" da mesma linha — há uma só versão viva, com auditoria de mudanças em `_log_alteracoes`.

A questão "que snapshot consultar" deixa de existir. Resta decidir como ler.

## Decisão

### Pagamentos: leitura direta da tabela viva

Qualquer KPI sobre pagamentos lê do estado atual de `_raw_pagamentos`:

```sql
SELECT ... FROM _raw_pagamentos WHERE parcelas_disponivel BETWEEN d1 AND d2
```

Não há vistas duplicadas, não há "qual snapshot". É sempre a verdade mais recente.

**Implicação prática:** se uma anulação retroativa entrar num snapshot futuro, o KPI histórico desse mês muda ligeiramente. Por exemplo, "MRR de Março 2026" pode descer de €20.450 para €20.405 quando uma anulação tardia for processada em Junho. Este movimento é:

- **Pequeno em magnitude** — ~3% das linhas/ano são mutáveis dentro de 365 dias; em meses individuais o impacto típico é <2%.
- **Informação útil, não bug** — significa que aconteceu uma anulação tardia. Se a gerente reparar e perguntar porquê, `_log_alteracoes` responde.
- **Auto-limitante no tempo** — passados 12 meses sobre o `pag_data` original, a linha está congelada (sem exemplos no histórico de 11 anos).

### Presenças: leitura direta da tabela

Igual ao desenho original. Eventos são imutáveis (ADR 0002, regime INSERT OR IGNORE):

```sql
SELECT ... FROM _raw_presencas WHERE data BETWEEN d1 AND d2
```

Não há escolha. A "atualidade" da resposta é limitada apenas pelo último upload — se a gerente só carregou presenças até 13-Mai, perguntas sobre 14-Mai retornam vazio. O dashboard mostra a data do último upload como contexto.

### Indicador de freshness no dashboard

Para que a gerente entenda o que está a ver, o dashboard mostra em todas as vistas:

> Pagamentos: dados de **2026-05-26 14:32** (último snapshot).
> Presenças: dados até **2026-05-13** (último snapshot disponível).

Quando a freshness fica desactualizada (ex: presenças com mais de 30 dias), aviso suave a sugerir nova extração.

## Consequências

**Ganhos:**
- **Implementação trivial.** Sem vistas materializadas, sem regras condicionais "se é mês corrente lê α senão β". Cada KPI é um `SELECT` simples.
- **Performance excelente.** Tabela de pagamentos tem ~110k linhas hoje e cresce ~15k/ano. Queries em milissegundos sem otimização especial.
- **Mental model único para a gerente.** "O dashboard mostra o que está na BD agora." Sem explicar "mês fechou em β", "vista live em α".

**Custos:**
- **KPIs históricos mexem quando anulações tardias entram.** Aceitável — magnitude pequena, informação útil. O log preserva a história das alterações para auditoria.
- **Não há "fecho de mês" automático.** Se for preciso reporting auditado no futuro, será necessário criar um mecanismo de snapshot manual ("congela o estado de Março nesta data"). Hoje não é necessidade.

## Para o código (`src/`)

- Funções de KPI continuam a receber DataFrames. Não sabem da BD.
- Uma camada nova (provavelmente `src/repository.py`) expõe:
  - `pagamentos(mes_de=None, mes_ate=None) -> pd.DataFrame`
  - `presencas(d1=None, d2=None) -> pd.DataFrame`
  - `metadados_snapshots() -> pd.DataFrame` (para o cartão de freshness)
- A migração do código existente (`src/kpis.py`, `src/renovacoes.py`) é mecânica: substituir `load_pagamentos()` por `repository.pagamentos()`.

## Quando reabrir esta decisão

- Se a gerente começar a usar o dashboard para reporting formal com terceiros (auditor, conselho fiscal) onde "Março não pode mudar depois de fechado" é requisito explícito. Solução: introduzir snapshots de fecho manuais, sem alterar a tabela viva.
- Se aparecer uma fonte futura com mutabilidade longa e imprevisível que torne o UPSERT silencioso problemático. Cenário improvável; reavaliar caso a caso.

## Histórico de revisões

- 2026-05-26 (inicial): regras β + α, com vistas materializadas e degradação controlada.
- 2026-05-26 (reescrito): vista única atual. Motivada pela decisão de ADR 0002 de unificar a camada raw em event-log + UPSERT, que tornou redundante a complexidade da regra β.

## Alternativas rejeitadas (após a revisão do ADR 0002)

- **Manter β como vista cacheada por cima da tabela viva**: tecnicamente possível (cachear "primeiro valor que entrou na tabela para um dado mês"). Custo de código desproporcional ao benefício, e introduz o conceito "qual versão de MRR de Março estás a ver?" — que esta decisão queria precisamente eliminar.
