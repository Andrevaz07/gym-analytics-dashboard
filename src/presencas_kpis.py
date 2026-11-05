"""
Cálculo dos Kpis de presenças.

Conveções:

- Funções que devolvem socias ativas em risco de churn cruzando os dados de presenças e pagamentos.



"""

import sqlite3
import pandas as pd
import numpy as np

from src.socias import socias_atuais, ids_com_presenca_esperada

def socias_em_risco(conn: sqlite3.Connection, dias: int = 30) -> pd.DataFrame:
    #1. ultima prensença por sócia
    df = pd.read_sql_query(
        """SELECT utente_no_insc, MAX(data) as ultima_presenca 
        FROM _raw_presencas GROUP BY utente_no_insc""",
        conn,
        parse_dates=["ultima_presenca"]
    )
    #2. âncora = MAX global 
    ancora = df["ultima_presenca"].max()

    df["dias_ausente"] = (ancora - df["ultima_presenca"]).dt.days

    # Quem se espera no ginásio, segundo a extração mais recente. Filtrar
    # por `utente_status = 'A'` em SQL bastava-se a si próprio enquanto os
    # exports traziam o histórico todo; com a janela de 6 meses passou a
    # apanhar linhas antigas com estados podres — 40 das 184 sócias da
    # lista já tinham saído, e 15 estavam suspensas (ausência combinada,
    # não sinal de risco). Ver src/socias.py.
    esperadas = ids_com_presenca_esperada(socias_atuais(conn))

    df_pagamentos = pd.read_sql_query("""SELECT DISTINCT utente_no_insc
    FROM _raw_pagamentos
    WHERE inv_familia = 'Mensalidades'
      AND pag_anulado = 'Não'
      AND LOWER(inv_descricao) NOT LIKE '%online%'""",
    conn)
    df_pagamentos = df_pagamentos[df_pagamentos["utente_no_insc"].isin(esperadas)]

    # sócias com PT ativo — marcador de possível falso positivo:
    # algumas vêm para o PT e podem não registar entrada no torniquete (confirmado pela gerente).
    pt_ids = pd.read_sql_query("""SELECT DISTINCT utente_no_insc
    FROM _raw_pagamentos
    WHERE inv_familia = 'Personal Trainer' AND pag_anulado = 'Não'""",
    conn)["utente_no_insc"]
    pt_ids = pt_ids[pt_ids.isin(esperadas)]

    # data de inscrição (mais recente) por sócia — para excluir novas sem oportunidade de aparecer na janela
    insc = pd.read_sql_query("""SELECT utente_no_insc, MAX(utente_data_insc) AS data_insc
    FROM _raw_pagamentos GROUP BY utente_no_insc""",
    conn, parse_dates=["data_insc"])

    resultado  = df_pagamentos.merge(df[["utente_no_insc","ultima_presenca", "dias_ausente"]],
    on= "utente_no_insc",
    how= "left")

    resultado = resultado.merge(insc, on="utente_no_insc", how="left")

    

    # Um corte só, em `dias` (30 por omissão). Medido em Fev-Jun 2026,
    # 1 827 sócia-mês: das que estavam 30-59 dias sem vir, 30% saíram no
    # mês seguinte; das de 60+, 31%; das de 14-29, só 7% — abaixo da
    # média de 8%; das que vinham, 1%. Os níveis antigos (14 / 30 / 60)
    # separavam grupos que se comportam igual, e chamavam "perdidas" a
    # sócias que, sete em cada dez, continuavam a pagar.
    condicoes = [
        resultado["dias_ausente"].isna(),
        resultado["dias_ausente"] < dias,
    ]

    etiquetas = ["sem presença no periodo", "ativa"]

    resultado["flag"] = np.select(condicoes, etiquetas, default="risco")

    # marcar quem tem PT: nas "sem presença"/risco, pode ser PT sem registo de entrada (verificar), não desistência
    resultado["tem_PT"] = resultado["utente_no_insc"].isin(pt_ids)

    # excluir novas sócias sem oportunidade: têm de ter sido sócias pelo menos `dias` antes do fim dos dados
    corte_oportunidade = ancora - pd.Timedelta(days=dias)

    resultado = resultado[
        ((resultado["dias_ausente"] >= dias) | (resultado["dias_ausente"].isna()))
        & (resultado["data_insc"] <= corte_oportunidade)
    ]

    return resultado

    