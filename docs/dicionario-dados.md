# Dicionário de Dados — Export software de gestão

Fonte: ficheiros `Teste valores ate 2000.XLSX` e `teste +2000.XLSX`  
Última análise: Abril 2026  
Total de linhas: 6.557 | Total de sócias únicas: 1.815

---

## Legenda de Estado

| Símbolo | Significado |
|---------|-------------|
| ✅ Confirmado | Valor e significado verificados nos dados |
| ⚠️ Inferido | Hipótese com base na análise — **confirmar com a gerente** |
| ❓ Por confirmar | Significado desconhecido — **obrigatório perguntar ao software de gestão** |

---

## Colunas do Export

### Grupo: Sócia (Utente)

| # | Nome da Coluna | Tipo | Valores Observados | Significado | Estado |
|---|----------------|------|--------------------|-------------|--------|
| 1 | **Utente Status** | texto | `A`, `M`, `S`, `P`, `D` | Estado atual da sócia. `A` = Ativa, `M` = Morta (inativa). `S`, `P`, `D` — significado desconhecido (poucos casos: 22, 19, 9 respetivamente) | ✅ `A` e `M` confirmados. ❓ `S`, `P`, `D` por confirmar |
| 2 | **Utente Nº Insc** | número | ex: `3`, `491`, `2574` | Número de inscrição único da sócia. Chave identificadora de cada pessoa | ✅ |
| 3 | **Utente Nome** | texto | ex: `Maria Exemplo` | Nome completo da sócia | ✅ |
| 7 | **Utente Data Insc.** | data | 2009-03-03 a 2025-10-07 | Data em que a sócia se inscreveu no ginásio pela primeira vez. Não muda com renovações | ✅ |
| 8 | **Utente Tipo Sócio** | texto | `Individual`, `Family`, `Corporate`, `Prospects` | Tipo de adesão. `Individual` = sócia a título pessoal. `Family` = plano família. `Corporate` = empresa. `Prospects` = potencial sócia ainda não inscrita | ✅ |
| 9 | **Utente Perfil** | texto | `Plano GINÁSIO`, `GOLD`, `PACK FAMILIA`, `1x SEMANA`, etc. | Etiqueta do plano/perfil atribuído à sócia. Não é o serviço — é uma categoria. Uma sócia pode ter várias linhas com o mesmo Perfil (cada uma = um serviço diferente) | ⚠️ |
| 23 | **Utente Gestor** | texto | `Gestora A`, `Gestora B`, `gerente`, etc. | Funcionária do ginásio responsável pela conta da sócia | ✅ |
| 37 | **Utente Dependência** | texto | `a unidade` (todas) | Instalação/unidade do ginásio. Todas as sócias pertencem a a unidade — sem variação neste export | ✅ |

---

### Grupo: Contrato

| # | Nome da Coluna | Tipo | Valores Observados | Significado | Estado |
|---|----------------|------|--------------------|-------------|--------|
| 5 | **Contrato Desde** | data | 2011-05-01 a 2026-04-01 | Data de início do contrato **atual** (esta linha específica). Nas sócias migradas em Agosto 2018, esta data reflete a migração, não a inscrição original | ✅ |
| 6 | **Contrato Até** | data / vazio | 2011-09-30 a 2026-05-01, ou vazio | Data de fim do contrato. **Vazio = contrato ainda em vigor, sem data de término definida**. Quando preenchida e no passado = contrato histórico | ✅ |
| 10 | **Contrato Desconto** | texto | `Sem desconto`, `Corporate`, `Pack Familia`, `Inscrição Amiga -50%`, `Congelamento 50%` | Tipo de desconto aplicado ao contrato. A maioria não tem desconto | ✅ |
| 11 | **Contrato Multa** | texto | `None` (6.556 linhas), `Multa` (1 linha) | Indicador de multa de incumprimento. Praticamente não usado | ✅ |
| 12 | **Contrato Modo Pag** | texto | `Transf. Banc. c/1º Pag. Inst.`, `Totalidade por Transf. Banc.`, `Nas Instalações` | Forma de pagamento do contrato. `c/1º Pag. Inst.` = transferência com primeira prestação nas instalações. `Totalidade` = pago de uma vez | ✅ |
| 13 | **Contrato Banco** | texto | vazio em todas as linhas | Banco associado ao débito direto. Não utilizado neste ginásio (todas por transferência) | ✅ |
| 17 | **Contrato Obs.** | texto | variado, maioritariamente vazio | Campo de observações livres preenchido manualmente. Sem padrão consistente | ⚠️ |
| 18 | **Contrato Comissionista** | texto | `Gestora B`, `Gestora A`, `gerente`, etc. | Funcionária que angariou ou é responsável pela comissão deste contrato | ✅ |
| 21 | **Contrato Manter Preço** | texto | `Manter o preço da data início do contrato`, `Seguir as datas definidas no inventário` | Define se a sócia mantém o preço original do contrato ou acompanha as atualizações de preço do ginásio. Explica por que há sócias a pagar preços diferentes pelo mesmo serviço | ✅ |
| 24 | **Contrato Periodicidade** | texto | `Mensal-Geral` (96%), `Mensal dia 5`, `Mensal dia 12` | Periodicidade de faturação. **Atenção: todas aparecem como mensais, mas podem existir planos trimestrais/semestrais/anuais que o sistema processa mensalmente.** Necessário confirmar com o software de gestão se existe outro campo ou relatório com a duração real do compromisso | ⚠️ **Bloqueador para cálculo de MRR real** |
| 25 | **Contrato Tipo** | texto | `N` (5.887), `A` (661), `R` (9) | ❓ Significado exato desconhecido. Hipótese: `N` = Normal/Novo, `A` = Anual, `R` = Renovação. Pode ser a chave para identificar planos anuais vs mensais | ❓ **Perguntar ao software de gestão** |
| 26 | **Contrato Data Renov.** | data | variado | Data prevista ou última renovação do contrato | ⚠️ |
| 27 | **Contrato Data Início** | data | 2009 a 2025 | Data em que a sócia iniciou a **relação com o ginásio** (contrato original). Para sócias antigas migradas em 2018, esta data é anterior a `Contrato Desde` | ✅ |
| 28 | **Contrato Identificador** | número | ex: `4.0`, `3387.0` | ID único do contrato no sistema software de gestão. Um contrato pode ter várias linhas (uma por serviço) | ✅ |
| 29 | **Contrato Data Assinatura** | data | variado | Data em que o contrato foi assinado pela sócia | ✅ |
| 30 | **Contrato Data Activação** | datetime | ex: `2025-12-22 12:05:18` | Timestamp da **última modificação** do registo no sistema. Não representa uma data de negócio — é metadado interno do software de gestão. Dois picos em massa: Dezembro 2025 e Fevereiro 2026 (provavelmente operações de manutenção em bloco) | ✅ Não usar para KPIs |
| 32 | **Contrato Origem** | texto / número | vazio (90%), alguns IDs numéricos | ❓ Significado desconhecido. Nos casos preenchidos, parece ser um ID de referência. Muito poucos casos | ❓ |
| 34 | **Contrato Última Parcela** | texto | `Sim`, `Não` | ❓ Indica se esta é a última parcela do contrato? Ou se a última parcela foi paga? Necessário confirmar | ❓ |
| 35 | **Contrato Total Pagadores** | número | `1` em todas as linhas | Número de pagadores do contrato. Sempre 1 — sem contratos partilhados | ✅ Não relevante |
| 36 | **Contrato Usa ADC Terceiro** | texto | `Não` em todas as linhas | Indicador de débito direto por terceiros. Não utilizado | ✅ Não relevante |

---

### Grupo: Fatura / Inventário (Inv.)

| # | Nome da Coluna | Tipo | Valores Observados | Significado | Estado |
|---|----------------|------|--------------------|-------------|--------|
| 0 | **Proc.** | texto | `P - Processada` (todas) | Estado do processamento da fatura. Todas processadas — sem variação neste export | ✅ Não relevante |
| 4 | **Inv. Descrição** | texto | `Mensalidade GINÁSIO`, `Aulas GOLD`, `Cacifo mensal`, etc. | Nome do serviço contratado. É o campo mais granular — descreve exatamente o que a sócia paga. 29 descrições únicas encontradas | ✅ |
| 14 | **Inv. Cód. barras** | texto | ex: `GOLD`, `AG`, `41`, `AF` | Código interno do produto/serviço no software de gestão. Pode ser usado como chave alternativa à descrição | ⚠️ |
| 15 | **Inv. Tipo item** | texto | `Mensalidades` (todas) | Tipo de item faturado. Todas as linhas deste export são mensalidades — outros tipos (ex: inscrições, serviços avulso) não foram exportados ou não existem | ✅ |
| 19 | **Inv. Valor Unitário** | decimal | ex: `41.46`, `15.45` | Valor sem IVA ou valor base antes de desconto. Diferente do PVP | ⚠️ Confirmar cálculo |
| 20 | **Inv. Valor PVP** | decimal | 3.44€ a 142€ | **Valor que a sócia paga** pelo serviço. Campo a usar para cálculo de MRR e ARPU | ✅ |
| 22 | **Inv. Família** | texto | `Mensalidades`, `Avaliações`, `Nutrição`, `Personal Trainer`, `kids`, `Cacifos`, `Cursos`, vazio | Categoria do serviço. Base para os buckets do dashboard. Metade das linhas está vazia — necessário mapear manualmente | ⚠️ Útil mas incompleto |
| 33 | **Inv. Activo** | texto | `Sim`, `Não` | Indica se **esta linha de fatura** está ativa no sistema. `Sim` = fatura ativa. `Não` = fatura desativada (histórico). **Atenção: não equivale a contrato ativo** — há linhas com `Sim` e datas já passadas. Usar sempre em conjunto com `Contrato Até` | ✅ |

---

### Grupo: Perfil

| # | Nome da Coluna | Tipo | Valores Observados | Significado | Estado |
|---|----------------|------|--------------------|-------------|--------|
| 31 | **Perfil Tipo** | texto | `Mensal. Base`, `Nutrição`, `Mensal. Extra I`, `Mensal. Extra II`, vazio | Classificação do tipo de serviço atribuída pelo software de gestão. `Mensal. Base` = mensalidade principal. Metade das linhas está vazia (incluindo cacifos, personal trainer, avaliações) — campo preenchido de forma inconsistente | ⚠️ Incompleto — ver Inv. Família |

---

### Grupo: Funcionário (Emp.)

| # | Nome da Coluna | Tipo | Valores Observados | Significado | Estado |
|---|----------------|------|--------------------|-------------|--------|
| 16 | **Emp. Nome** | texto | `RPonte`, `Gestora B`, `acachaco`, `dmata`, etc. | Username ou nome do funcionário que registou ou processou o contrato no sistema. Alguns nomes aparecem duplicados com grafias diferentes (ex: `RPonte` e `Gestora B` são a mesma pessoa) | ✅ |

---

## Filtro para Contratos Ativos (MRR)

Para obter as linhas que representam contratos **atualmente em vigor**, usar:

```
Utente Status = "A"
AND Inv. Activo = "Sim"
AND (Contrato Até está vazio OU Contrato Até >= data de hoje)
```

**Resultado com os dados atuais:** 238 sócias únicas

---

## Campos a Confirmar com a Gerente / software de gestão

| Campo | Pergunta |
|-------|----------|
| Utente Status `S`, `P`, `D` | O que significa cada um destes estados? |
| Contrato Tipo `N`, `A`, `R` | O que representa cada tipo? (hipótese: N=Normal, A=Anual, R=Renovação) |
| Contrato Periodicidade | Todos os contratos aparecem como mensais — existem planos trimestrais/semestrais/anuais? Onde estão guardados no sistema? |
| Contrato Última Parcela | O que significa `Sim`/`Não` neste campo? |
| Contrato Origem | O que são os IDs numéricos neste campo? |
| Inv. Família (vazio) | Pode ser preenchido na exportação? Ou é um campo opcional? |
| Contrato Desde vs Data Início | O que aconteceu em Agosto 2018? Houve migração de sistema ou mudança de instalações que justifique as duas datas diferentes? |

---

## Buckets de Serviços Propostos

Com base na coluna `Inv. Descrição` e na proposta do projeto:

| Bucket | Descrições incluídas |
|--------|---------------------|
| **Atividade Física** | Mensalidade GINÁSIO, Mensalidade GINÁSIO 25, Aulas GOLD, AULAS DE GRUPO, Plano 1X semana, Plano 1X semana 25, Plano Pack família, Plano Pack família 25, Mensalidade Online |
| **Kids** | Plano KID Ballet 1 25, Plano KID B 25, Plano KID karaté, Plano KID karaté 25, Plano PFKID Ballet 1 25, Plano PFKID Karaté, Plano PFKID B 25, Kid Extra Ballet, Kid Extra B |
| **Personal / Treino Individual** | Treino Individual Pilates, Acompanhamento Individual, Pilates Avançado 23 |
| **Nutrição** | Nutricoaching 4, Prog Nutri 25 |
| **Avaliações / Scans** | Consulta Avaliação, Consulta Scan Mensal Sc, Consulta Scan Mensal Sc 25 |
| **Cacifos** | Cacifo mensal |
| **Pack Família** | Pack família |

> ⚠️ Buckets a validar com a gerente antes de usar no dashboard
