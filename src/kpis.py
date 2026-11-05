"""
Cálculo dos KPIs de negócio do ginásio.


Convenções:
- Funções que devolvem conjuntos(foudation) usam ´set´ de ´utente_no_insc´
- Funções que devolvem contagens prefixam-se com ´n_´.
- O eixo temporal histórico é ´parcelas_diponivel´ (mes de serviço),
    Os pagamentos anuais distruibuem-se em N linhas,
    uma por mês de cobertura - o pandas trata cada uma como activa.

- Filtro estrutural : ´pag_anulado == "Não´  em todas as funções de receita/contagem.

"""

import pandas as pd

#-------------------------------------------------------------
# Regra de negócio - definação de "sócia ativa"
#-------------------------------------------------------------

# Uma sócia é ativa num mês M se:
#   - Tem inv_familia em PLANOS_PRINCIPAIS no mês M, OU
#   - Tem AMBAS as famílias do PACK_NUTRICAO no mês M.

PLANOS_PRINCIPAIS = ["Mensalidades", "Personal Trainer", "kids"]
PACK_NUTRICAO = ["Avaliações", "Nutrição"]

# Familias cuja receita conta para MRR (recurrencia periodica
FAMILIAS_MRR = PLANOS_PRINCIPAIS + PACK_NUTRICAO

# -------------------------------------------------------------
# Foundation — conjuntos de sócias por mês
# -------------------------------------------------------------

def socias_ativas_no_mes(df: pd.DataFrame, mes_periodo : pd.Period) -> set[int]:

    """
    Conjunto de IDs de sócias ativas para um dado mês.

    Uma sócia conta como ativa em M se, durante M, pagou alguma das
    familias em PLANOS_PRINCIPAIS, ou pagou ambas as familias de 
    PACK_NUTRICAO(Avaliações + Nutrição em conjunto formam um pack de
    serviço autonomo).

    Args:
        df: DataFrame de pagamentos limpos(output de clean_pagamentos).
        mes_periodo: Periodo mensal alvo, ex: pd.Period("2026-05","M").

    Returns:
        set[int]: IDs unicos (utente_no_insc) das sócias activas em M.


    Notas:
        Eixo temporal: parcelas_disponivel (mes de serviço).Filtra
        pag_anulado == "Não". Não usa utente_status - esta função é 
        temporal, nao snapshot.

    """

    df_mes = df[
        (df["parcelas_disponivel"].dt.to_period("M") == mes_periodo)
        & (df["pag_anulado"] == "Não")    
    ]

    com_plano = set(
        df_mes[df_mes["inv_familia"].isin(PLANOS_PRINCIPAIS)]["utente_no_insc"].dropna()
    )

    com_aval = set(df_mes[df_mes["inv_familia"] == "Avaliações"]["utente_no_insc"].dropna())
    com_nutri = set(df_mes[df_mes["inv_familia"] == "Nutrição"]["utente_no_insc"].dropna())


    return com_plano | (com_aval & com_nutri)


# `socias_ativas_snapshot` viveu aqui até 2026-09-07. Foi para
# src/socias.py porque a resposta certa não cabe num DataFrame de
# pagamentos: além do estado mais recente de cada sócia, é preciso saber
# quem veio na última extração — e isso está em _raw_snapshots. A versão
# que existia aqui contava 413 sócias quando eram 380, incluindo doze que
# não pagam nada desde Junho de 2022.


# ---------------------------------------------------------------------------
# Contagens — KPIs escalares prontos para o dashboard
# ---------------------------------------------------------------------------

def n_socias_ativas_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> int:
    """ Número de sócias ativas no mes dado."""

    return len(socias_ativas_no_mes(df, mes_periodo))



def mrr_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> float :
    """
    Receita recorrente do mes dado (Monthly Recurring Revenue).

    Soma de parcelas_valor_liquido, para linhas com parcelas_disponivel em M,
    pag_anulado == "Não" e inv_familia em FAMILIAS_MRR. Anuais pagos numa unica vez
    distribuem-se naturalmente porque o software de gestão gera uma linha por mes de cobertura.


    Args:
        df: DataFrame de pagamentos limpos.
        mes_periodo: Periodo mensal alvo.


    Returns:
        float: Receita do mes em euros(Sem IVA).

    """

    mask = (
        (df["parcelas_disponivel"].dt.to_period("M") == mes_periodo)
        & (df["pag_anulado"] == "Não")
        & (df["inv_familia"].isin(FAMILIAS_MRR))
    )

    return float(df.loc[mask,"parcelas_valor_liquido"].sum())



def faturacao_total_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> float:
    """
    Faturação total do mês — todas as famílias, sem anuladas, sem IVA.

    Diferente do MRR: inclui rubricas one-off (Inscrições), loja (Prozis,
    Captain Kombucha, etc.), cacifos e qualquer outra família que não
    seja recorrente. Mede o caixa efetivo do mês, não a previsibilidade
    da subscrição.

    Args:
        df: DataFrame de pagamentos limpos.
        mes_periodo: Período mensal alvo.

    Returns:
        float: Faturação em euros (sem IVA).
    """
    mask = (
        (df["parcelas_disponivel"].dt.to_period("M") == mes_periodo)
        & (df["pag_anulado"] == "Não")
    )
    return float(df.loc[mask, "parcelas_valor_liquido"].sum())


def arpu_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> float:
    """
    Receita média por sócia ativa no mês dado ( Average Revenue Per User)

    ARPU = mrr_no_mes / n_socias_ativas_no_mes. O denominador é o mesmo
    KPI "Sócias Ativas" mostrado no Dashboard, para os numeros fecharem de forma
    coerente para a gerente.
    

    Args:
        df: DataFrame de pagamentos limpos.
        mes_periodo: Periodo mensal alvo.


    Returns:
        float: Receita media por socia em Euros. Devolve 0.0 se não houver sócias ativas
        no mes, para evitar divisao por zero
    """
    n_socia = n_socias_ativas_no_mes(df, mes_periodo)

    if n_socia == 0:
        return 0.0

    return mrr_no_mes(df, mes_periodo) / n_socia


# ---------------------------------------------------------------------------
# Fluxo de sócias — entradas e saídas mês a mês
# ---------------------------------------------------------------------------


def socios_perdidos_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> set[int]:
    """
    Socias que estavam ativas no mes anterior mas não no mês dado.


    Diferença de conjuntos: ativas(M-1) - ativas(M). É base do churn 
    e da watchlist de renovação. NOTA: para o mes corrente (parcial) este
    conjunto vem infalcionado, porque socias Activas(M) ainda esta incompleto(sócias
    que pagam depois do snapshot). Só é fiavel para meses fechados.

    Args:
        df: DataFrame de pagamentos limpos.
        mes_periodo: Periodo mensal alvo.

    Returns:
        set[int]: IDs das socias perdidas em M.
    """
    
    return socias_ativas_no_mes(df, mes_periodo - 1) - socias_ativas_no_mes(df,mes_periodo)



def novos_socios_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> set[int]:
    """
    Socias que passaram a estar ativas no mes dado face ao anterior.

    Diferença de conjuntos: ativas(M) - ativas(M-1). Inclui inscrições 
    novas e reativações(sócias que voltaram).

    Args: 
        df: DataFrame de pagamentos limpos.
        mes_periodo: Periodo mensal alvo.

    Returns:
        set[int]: IDs das socias novas/reativadas em M.

    """

    return socias_ativas_no_mes(df,mes_periodo) - socias_ativas_no_mes(df,mes_periodo - 1)


def n_socios_perdidos_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> int:

    """Numero de socias perdidas em M (ver socios_perdidos_no_mes)."""

    return len(socios_perdidos_no_mes(df,mes_periodo))


def n_novos_socios_no_mes(df: pd.DataFrame, mes_periodo: pd.Period) -> int:
    """Numero de socias novas em M """

    return len(novos_socios_no_mes(df, mes_periodo))


# ---------------------------------------------------------------------------
# Retenção, churn e valor de vida
# ---------------------------------------------------------------------------


def taxa_churn(df: pd.DataFrame, mes_periodo: pd.Period) -> float:
    """
    Percentagem de socias perdidas em M face as activas no inicio do mes.

    churn(M-1) = n_perdidos(M) / n-ativas(M-1) * 100. O denominador é activas(M-1)
    as socias no inicio de M. Devolve 0.0 se nao houver socias no mes anterior.

    NOTA: Só é fiavel para meses fechados. Para o mes corrente o numerador (perdidos)
    vem inflaciodao pela data freshness, aumentando o churn.

    Args:
        df: DataFrame de pagamentos limpos.
        mes_periodo: Periodo mensal alvo.


    Returns:
        float: Taxe de churn em percentagem.

    """

    base = n_socias_ativas_no_mes(df, mes_periodo - 1)
    if base == 0:
        return 0.0

    return n_socios_perdidos_no_mes(df,mes_periodo) / base * 100.0


def taxa_retencao(df: pd.DataFrame, mes_periodo: pd.Period) -> float:

    """
    Percentagem de socias retidas em M.

    retencao(M) = 100 - churn(M)

    Args:
        df: DataFrame de pagamentos limpos.
        mes_periodo: Periodo mensal alvo.

    Returns:
        float: Taxa de retencao em percentagem.
        
    """

    return 100.0 - taxa_churn(df, mes_periodo)


def ltv_estimado(arpu: float, taxa_churn_pct: float) -> float:
    """
    Valor de vida estimado de uma socia (Life Time Value).

    LTV = ARPU * tempo de vida medio, onde tempo mde vida (em meses) é 
    1 / churn_fração. Equivale a ARPU / (taxa_churn_pct / 100)


    Funçao Pura: Recebe ARPU e Churn ja calculados(idealmente medias de varios meses,
    nao de um mes isolado, porque churn mensal é volatil.)
    Devolve 0.0 se o churn for 0.

    Args:
        arpu: receta media por socia(€/mes)-
        taxa_churn_pct: Taxa de churn mensal em percentagem.


    Returns:
        float: LTV estimado em euros.
    """
    if taxa_churn_pct == 0.0:
        return 0.0
    return arpu / (taxa_churn_pct / 100.0)

# Nota: as listas accionáveis ("sócias a renovar", "sócias em atraso") vivem
# sobre os dados de CONTRATOS (Contrato Até / Periodicidade), não pagamentos.
# Ver notebook 03_recon_contratos e o futuro módulo de contratos.

    