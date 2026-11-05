"""Limpeza estrutural pós-ingestion."""


import pandas as pd 


def clean_pagamentos(df: pd.DataFrame) -> pd.DataFrame:
    """
    Remove linhas estruturalmente inválidas.
    
    Regras (validadas no notebook 02_recon_pagamentos secção 2):
    - Sem pag_no_pag - linhas lixo do export(subtotais/órfãs)
    - Sem pag_data - não entra em nenhum KPI temporal


    Args:
        df: DataFrame retornado por load_pagamentos().

    Returns:
        DataFrame com índice reset. Tipicamente ~50% das linhas removidas.
    """

    mask = df["pag_no_pag"].notna() & df["pag_data"].notna()

    return df[mask].reset_index(drop=True)


    

