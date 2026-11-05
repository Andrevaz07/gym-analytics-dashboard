# ADR 0001 — BD acumuladora de snapshots (B), com porta aberta para modelo curado (C)

**Data:** 2026-05-26
**Estado:** Aceite

## Contexto

Os dados chegam por export manual de CSV do software de gestão. Cada export é uma *fotografia integral* do estado da fonte na data em que foi tirado. A construção do dashboard precisa de responder a duas classes de pergunta:

1. **Estado atual** — quantas sócias ativas hoje, MRR deste mês, lista a renovar no próximo mês.
2. **Evolução temporal** — MRR mês a mês, churn nos últimos 12 meses, retenção por coorte.

Durante a análise descobrimos duas limitações dos exports que tornam a evolução temporal incerta se confiarmos só no último ficheiro:

- O `utente_status` é destrutivo: uma sócia que estava `A` em Abril e está `M` em Maio aparece apenas como `M` no export de Maio. A informação "estava ativa em Abril" só é recuperável re-inferindo das linhas de pagamento — o que já mostrou ser frágil e mudou de definição duas vezes.
- Os pagamentos podem ser anulados retroativamente. Uma linha que era `pag_anulado == "Não"` num export pode aparecer como `"Sim"` num export posterior. Sem guardar o estado anterior, perdemos a verdade do que sabíamos no momento.

Considerámos três arquétipos:

- **A — BD como cache derivada.** Cada export substitui o conteúdo. Simples, mas perde toda a fidelidade temporal não-derivável.
- **B — BD acumuladora de snapshots.** Cada export é guardado como snapshot carimbado com `snapshot_data`. KPIs históricos lêem do snapshot adequado. Schema simples; KPIs continuam em Python.
- **C — Landing raw + modelo dimensional curado.** Camada `_raw_*` igual a B, mais `dim_*` / `fct_*` com SCD2. KPIs vivem em SQL. Maior performance e elegância em queries temporais; custo upfront de 1-2 semanas e perda de flexibilidade enquanto as regras de negócio ainda mudam.

## Decisão

Adoptar **B**: BD com snapshots acumulados, sem modelo dimensional.

Constraints de design que mantêm a porta aberta para C:

- Tabelas raw têm prefixo `_raw_` e `snapshot_data` como coluna explícita (não sufixo no nome).
- A chave natural `utente_no_insc` é usada diretamente; não criar IDs sintéticos antes de existir um modelo dimensional que os justifique.
- Pagamentos e utentes ficam em tabelas separadas — mesmo que cada snapshot venha de um único ficheiro de pagamentos, não fundir.
- KPIs ficam em funções Python que recebem DataFrames, não em SQL. Migrar para C significa empurrar essas funções para baixo (transform.py) sem alterar a assinatura externa.

## Consequências

**Ganhos:**
- Verdade temporal preservada. "O que sabíamos a 13-05" é exatamente o snapshot de 13-05.
- Mudanças de regra de negócio (já aconteceram duas vezes em 4 semanas) recomputam-se em Python sem migrações de schema.
- Caminho de evolução claro: quando o dashboard estiver estável e o domínio maduro, adiciona-se a camada curada por cima sem mexer no raw.

**Custos:**
- Queries de evolução temporal (12+ meses) varrem repetidamente o histórico. Aceitável enquanto Streamlit tem caching e o utilizador é único (gerente).
- Cada snapshot duplica a maior parte das linhas de pagamento. Para 12 snapshots de ~190k linhas, fala-se de ~2-3M linhas em SQLite — confortável.
- O conceito de "qual snapshot consultar para o mês M" não é trivial e tem de ser definido (provavelmente: o primeiro snapshot que cubra M, congelando a verdade do fecho de mês). Decisão adiada para ADR próprio quando for forçada.

## Sinais para promover a C

Reavaliar quando *qualquer* destes se verificar:

- Dashboard regularmente acima de 2-3s a carregar.
- Três ou mais módulos a duplicarem lógica de "estado a data X" em vez de consultarem uma vista temporal.
- Aparece uma segunda fonte (acessos, contratos definitivos, API o fornecedor do software) que faz sentido juntar a montante das funções de KPI.
- A gerente pede gráficos de evolução de 12+ meses que se tornam o uso dominante do dashboard.

## Alternativas rejeitadas

- **A** (cache derivada): perde fidelidade histórica que é exatamente o problema que motivou a BD.
- **C** (curado upfront): otimiza performance e elegância que ainda não são restrições reais, congela um modelo dimensional antes de o domínio estabilizar (definição de "ativa" e fonte das listas já mudaram duas vezes em 4 semanas).
