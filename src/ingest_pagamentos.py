""" Ingestão de pagamentos para a BD.

Fase 1 : Apenas insere; assume tabela vazia ou linhas que não conflitam.
Upsert real e log de alterações entram em interações posteriores.

"""

from __future__ import annotations
from pathlib import Path
from datetime import date
import sqlite3
import pandas as pd

from src.ingestion import load_pagamentos
from src.clean import clean_pagamentos
from src.db import conectar, criar_schema
from src.ingest_common import hash_ficheiro, snapshot_existente

def _normalizar(valor) -> str | float | None :
    """
    Põe um valor (vindo do df OU do Sqlite) numa forma canónica
    comparável. Usado para detetar se um campo mutável mudou entre
    o snapshot novo e o que ja esá na BD
    """

    if pd.isna(valor):
        return None
    if isinstance(valor, pd.Timestamp):
        return valor.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(valor, str):
        return valor
    return float(valor)


# Campos do EVENTO pagamento que a fonte pode reescrever (ADR 0002).
# Mudanças nestes campos são auditadas em _log_alteracoes.
CAMPOS_EVENTO = ["pag_anulado", "pag_data_anulacao", "parcelas_valor_liquido"]

# Campos da DIMENSÃO utente: o export desnormaliza o estado ATUAL da
# sócia em todas as linhas dela. Não descrevem o evento — seguem sempre
# o snapshot mais recente, SEM log (mudam em massa a cada export).
CAMPOS_UTENTE = [
    "utente_status", "utente_gestor", "utente_tipo_socio",
    "doc_nome", "utente_data_insc",
]

# A ordem importa: os índices 0..2 do tuplo comparado são os campos de evento.
CAMPOS_COMPARADOS = CAMPOS_EVENTO + CAMPOS_UTENTE


def _estado_atual(conn: sqlite3.Connection) -> dict:
    """
    Lê o estado atual de _raw_pagamentos para um dicionário
    {no_parcela: (valores de CAMPOS_COMPARADOS)}.
    Usado para lookups O(1) durante o UPSERT
    """

    colunas = ", ".join(["no_parcela"] + CAMPOS_COMPARADOS)
    cursor = conn.execute(f"SELECT {colunas} FROM _raw_pagamentos")

    return {row[0]: row[1:] for row in cursor}

    



#Colunas que vão para BD na mesma ordem do schema.criar_schema.
# pag_meio_pagamento ainda nao está no USECOLS - fica NULL por agora.criar_schema

COLUNAS_BD = [
    "no_parcela", "pag_no_pag", "pag_data", "pag_anulado",
    "pag_data_anulacao", "parcelas_disponivel", "parcelas_descricao",
    "parcelas_valor_liquido", "parcelas_promocoes", "inv_familia",
    "inv_descricao", "utente_no_insc", "utente_status", "utente_data_insc",
    "doc_nome", "utente_gestor", "utente_tipo_socio",
]


def ingest_pagamentos(
    path : Path,
    snapshot_data: date,
    conn: sqlite3.Connection,
) -> dict:
    """
    Ingere um CSV de pagamentos. Devolve estatisticas do que aconteceu.
    """


    # 0. Bloco de Segurança - Se o ficheiro já foi ingerido, não fazer nada.

    hash_novo = hash_ficheiro(path)

    hash_guardado = snapshot_existente(conn, snapshot_data, "pagamentos")

    if hash_guardado is not None:

        if hash_novo == hash_guardado:
            return {"inseridos": 0, "deduplicados": 0, "saltado": True}


        raise ValueError(
            f"Snapshot {snapshot_data} de pagamentos já foi ingerido com hash diferente. "
            f"Guardado:{hash_guardado[:12]}... novo: {hash_novo[:12]}..."
            f"Investiga antes de re-ingerir"
        )

    # 1. carregar e limpar.date
    df = load_pagamentos(path)
    df = clean_pagamentos(df)

    #2. deduplicar - artefacto do export em pagamentos anulados.clean_pagamentos
    n_antes = len(df)
    df = df.drop_duplicates(subset="no_parcela", keep="first")
    n_dedup = n_antes - len(df)

    #3. preparar para a BD: só as colunas do schema + atulização_em_snapshot
    df_bd = df[COLUNAS_BD].copy()
    df_bd["atualizado_em_snapshot"] = snapshot_data
    df_bd["pag_meio_pagamento"] = None   #por enquanto não temos isto

    #4. UPSERT: comparar snapshot novo com o que já esta na BD.

    existentes = _estado_atual(conn)

    novos = []
    atualizados = []
    ignorados = []
    log = [] # (no_parcela, snapshots, campo, valor_antigo, valor_novo) - 1 por campo mudado

    for linha in df_bd.itertuples(index=False):
        npq = linha.no_parcela
        antigo = existentes.get(npq)

        if antigo is None:
            novos.append(npq)
            continue

        # forma canónica dos dois lados, campo a campo, na mesma ordem
        novo  = [_normalizar(getattr(linha, campo)) for campo in CAMPOS_COMPARADOS]
        velho = [_normalizar(valor) for valor in antigo]

        if novo == velho:
            ignorados.append(npq)
            continue

        # linha mudou → UPDATE de todos os campos comparados + carimbo + chave (WHERE)
        atualizados.append((*novo, snapshot_data.isoformat(), npq))

        # auditar SÓ os campos do evento (índices 0..2); a dimensão utente
        # muda em massa a cada export e não é anomalia a investigar
        for i, campo in enumerate(CAMPOS_EVENTO):
            if novo[i] != velho[i]:
                log.append((npq, snapshot_data.isoformat(), campo, velho[i], novo[i]))

    # 4b. aplicar à BD

    cur = conn.cursor()

    # (1) NOVOS -> recuperar as linhas inteiras do df_bd e inserir em massa

    if novos : 
        df_novos = df_bd[df_bd["no_parcela"].isin(novos)]
        df_novos.to_sql("_raw_pagamentos", conn, if_exists="append", index=False)

    # (2) ATUALIZADOS -> UPDATE dos campos comparados + carimbo, por chave

    if atualizados:
        set_clausulas = ", ".join(f"{campo} = ?" for campo in CAMPOS_COMPARADOS)
        cur.executemany(
            f"""
            UPDATE _raw_pagamentos
            SET {set_clausulas},
                atualizado_em_snapshot = ?
            WHERE no_parcela = ?;
            """,
            atualizados,
        )

    # (3) LOG -> uma linha por campo mudado
    if log:
        cur.executemany(
            """
            INSERT INTO _log_alteracoes(no_parcela, snapshot_data, campo, valor_antigo, valor_novo)
            VALUES(?, ?, ?, ?, ?)
            """,
            log,
        )

    #5. registar o snapshot
    conn.execute(
        """
        INSERT INTO _raw_snapshots (
            snapshot_data, tabela, ficheiro_origem, hash_ficheiro,
            n_linhas, cobertura_de, cobertura_ate
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            snapshot_data.isoformat(),
            "pagamentos",
            path.name,
            hash_novo,  # 1.4b: calcular hash
            len(df_bd),
            df["pag_data"].min().date().isoformat(),
            df["pag_data"].max().date().isoformat(),
        ),
    )
    conn.commit()
    
    return {
        "inseridos": len(novos),
        "atualizados": len(atualizados),
        "ignorados": len(ignorados),
        "deduplicados": n_dedup,
        "alteracoes": len(log),
    }



if __name__ == "__main__":
    # Smoke test: ingere o snapshot histórico atual
    conn = conectar()
    criar_schema(conn)  # idempotente

    path = Path("data") / "snapshots" / "2026-05-13_pagamentos.xlsx"
    stats = ingest_pagamentos(path, date(2026, 5, 13), conn)
    print("Ingestão concluída:", stats)

    # Contagens de validação
    n_pag = conn.execute("SELECT COUNT(*) FROM _raw_pagamentos").fetchone()[0]
    n_snap = conn.execute("SELECT COUNT(*) FROM _raw_snapshots").fetchone()[0]
    print(f"Linhas em _raw_pagamentos: {n_pag:,}")
    print(f"Linhas em _raw_snapshots: {n_snap}")

    conn.close()