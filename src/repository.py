"""
Camada de acesso à BD: devolve DataFrames prontos para os KPIs.

Ver docs/adr/0003 - leitura direita da tabela viva.
"""

from __future__ import annotations
import sqlite3

import pandas as pd


#Colunas DATE/TIMESTAMP que precisam de ser convertidas ao ler.
#SQLite guardo como TEXTe (ISO); o pandas precisa de hint


DATE_COLS = [
     "pag_data",
    "pag_data_anulacao",
    "parcelas_disponivel",
    "utente_data_insc",
]


def pagamentos(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Lê toda a tabela _raw_pagamentos. Datas já em datetime.

    Fase 1: devolve tudo. Filtros (por mês, por sócia, etc.)
    entram quando o dashboard começar a pedir.
    """
    return pd.read_sql_query(
        "SELECT * FROM _raw_pagamentos",
        conn,
        parse_dates=DATE_COLS,
    )


if __name__ == "__main__":
    # Smoke test + validação contra ground truth do notebook 7.6
    from src.db import conectar
    from src.kpis import n_socias_ativas_no_mes, mrr_no_mes

    conn = conectar()
    df = pagamentos(conn)
    print(f"Linhas lidas: {len(df):,}")
    print()
    print("Tipos das colunas críticas:")
    print(df[["pag_data", "parcelas_disponivel", "utente_no_insc",
              "inv_familia", "pag_anulado"]].dtypes)
    print()

    # Retrato do último mês fechado. Os valores a esperar não estão fixos
    # aqui de propósito: cada extração nova traz pagamentos retroactivos e
    # move-os um pouco (Abril de 2026 passou de 425 para 427 quando chegou
    # o snapshot de Julho). Um número fixo envelhece e faz parecer avariado
    # o que está a funcionar.
    from src.historico import ultimo_mes_fechado
    mes = ultimo_mes_fechado(df["pag_data"].max())
    print(f"Último mês fechado: {mes}")
    print(f"  sócias ativas : {n_socias_ativas_no_mes(df, mes)}")
    print(f"  MRR           : €{mrr_no_mes(df, mes):,.0f}")

    from src.renovacoes import listas_renovacao
    from src.socias import socias_atuais, ids_socias
    ativas = ids_socias(socias_atuais(conn))
    listas = listas_renovacao(df, ativas=ativas)
    print(f"\nSócias agora (A+S, vistas na última extração): {len(ativas)}")
    print(f"Lista de renovação (mês seguinte ao snapshot): {len(listas)}")

    conn.close()
