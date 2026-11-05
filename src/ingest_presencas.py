"""Ingestão de presenças (acessos) para a BD. Event-log com INSERT OR IGNORE."""


from __future__ import annotations
from pathlib import Path
from datetime import date
import sqlite3

from src.ingestion import load_acessos
from src.db import conectar, criar_schema
from src.ingest_common import hash_ficheiro, snapshot_existente



# colunas da tabela, na ordem do INSERT (sem ingerido_em_snapshot)
COLUNAS_BD = [
    "utente_no_insc",
    "data", "hora_entrada", "utente_nome",
    "turma_nome", "utente_perfil", "utente_estado_no_evento"
]


def ingest_presencas(path: Path, snapshot_data: date, conn: sqlite3.Connection) -> dict:
    """Ingere um snapshot de acessos. Devolve Estatisticas."""


    # 0. guarda de idempotencia
    hash_novo = hash_ficheiro(path)
    hash_guardado = snapshot_existente(conn, snapshot_data, "presencas")
    if hash_guardado  is not None:
        if hash_novo == hash_guardado:
            return {"inseridos" : 0 , "ignorados" : 0, "saltado": True}

        raise ValueError(
            f"Snapshot {snapshot_data} de presenças já ingerido com hash diferente. "
            f"Guardado: {hash_guardado[:12]}... novo: {hash_novo[:12]}... Investiga."
        )


    # 1. carregar

    df = load_acessos(path)

    # 2. Preparar : renomear, converter tipos, filtrar PK, carimbar
    df = df.rename(columns={"utente_estado": "utente_estado_no_evento"})

    # 2a. (Movido para cima) as 3 colunas da PK nao podem ser nulas
    # Remove NaNs antes da conversão de timedelta para garantir que pandas usa int em vez de float
    df = df.dropna(subset=["utente_no_insc","data","hora_entrada"])

    # 2b. hora_entrada vem como timedelta (duração desde da meia noite) -> "HH:MM:SS"
    c = df["hora_entrada"].dt.components
    df["hora_entrada"] = ( 
        c["hours"].astype(str).str.zfill(2) + ":" +
        c["minutes"].astype(str).str.zfill(2) + ":" +
        c["seconds"].astype(str).str.zfill(2)
    )

    # 2c. data -> Texto ISO (a coluna é DATE)
    df["data"] = df["data"].dt.strftime("%Y-%m-%d")

    # 2d. carimbo do snapshot
    df_bd = df[COLUNAS_BD].copy()

    if df_bd.empty:
        return {"inseridos": 0, "ignorados": 0}

    df_bd["utente_no_insc"] = df_bd["utente_no_insc"].apply(int) #numpy.int32 -> int nativo (senão SQlite guarda BLOB)
    df_bd["ingerido_em_snapshot"] = snapshot_data.isoformat()

    
    # 3. INSERT OR IGNORE
    cur = conn.cursor()
    n_antes = conn.execute("SELECT COUNT(*) FROM _raw_presencas"
    ).fetchone()[0]

    colunas = COLUNAS_BD + ["ingerido_em_snapshot"]
    placeholders = ", ".join(["?"] * len(colunas))
    cur.executemany(
        f"INSERT OR IGNORE INTO _raw_presencas "
        f"({', '.join(colunas)})"
        f" VALUES({placeholders})",
        df_bd[colunas].itertuples(index=False, name=None)
    )

    n_depois = conn.execute("SELECT COUNT(*) FROM _raw_presencas"
    ).fetchone()[0]
    inseridos = n_depois - n_antes
    ignorados = len(df_bd) - inseridos

    #4. registar o snapshot
    conn.execute(
        """
        INSERT INTO _raw_snapshots(
            snapshot_data, tabela, ficheiro_origem, hash_ficheiro,
            n_linhas, cobertura_de,
            cobertura_ate
    ) VALUES (?, ?, ?, ?, ?, ?, ?) 
    """,(
            snapshot_data.isoformat(),
            "presencas",
            path.name,
            hash_novo,
            len(df_bd),
            df_bd["data"].min(),
            df_bd["data"].max(),
        ),
    )
    conn.commit()

    return {"inseridos": inseridos, "ignorados": ignorados}

if __name__ == "__main__":
    conn = conectar()
    criar_schema(conn) #idempotente

    path = Path("data") / "snapshots" / "2026-05-13_acessos.xlsx"
    stats = ingest_presencas(path, date(2026,5,13), conn)
    print("Ingestão concluída:",stats)

    n_press = conn.execute("SELECT COUNT(*) FROM _raw_presencas").fetchone()[0]
    print(f"Total de presenças agora na BD: {n_press}")

    conn.close()

