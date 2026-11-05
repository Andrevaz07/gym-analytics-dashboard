import pandas as pd
import pytest
from src.ingest_pagamentos import _normalizar
from src.db import conectar, criar_schema
from src.ingest_pagamentos import _estado_atual
from datetime import date
from src.ingest_pagamentos import _normalizar, _estado_atual, ingest_pagamentos


def test_normalizar_nat_vira_none():
    # Nat (data vazia do pandas) deve virar None
    assert _normalizar(pd.NaT) is None 

def test_normalizar_nan_vira_none():
    #NaN (numero vazio) vira None
    assert _normalizar(float("nan")) is None

def test_normalizar_timestamp_vira_string():
    #Timestamp vira string no formato do SQlite
    ts = pd.Timestamp("2026-06-01")
    assert _normalizar(ts) == "2026-06-01 00:00:00"

def test_normalizar_string_passa_igual():
    # Uma string ("Sim/Não") deve passar tal e qual
    assert _normalizar("Não") == "Não"


def test_estado_atual_bd_vazia_devolve_dict_vazio(db):
    # BD acabada de criar, sem linhas → dict vazio
    assert _estado_atual(db) == {}


def test_estado_atual_le_linhas_existentes(db):
    # inserir 2 linhas à mão (só as colunas obrigatórias + as 3 mutáveis)
    db.executemany(
        """
        INSERT INTO _raw_pagamentos (no_parcela, pag_anulado, pag_data_anulacao,
                                     parcelas_valor_liquido, atualizado_em_snapshot)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (101, "Não", None, 39.9, "2026-05-13"),
            (102, "Sim", "2026-04-20 00:00:00", 0.0, "2026-05-13"),
        ],
    )

    estado = _estado_atual(db)

    # tuplo segue CAMPOS_COMPARADOS: 3 campos de evento + 5 da dimensão
    # utente (não preenchidos neste INSERT → None)
    assert estado[101] == ("Não", None, 39.9, None, None, None, None, None)
    assert estado[102] == ("Sim", "2026-04-20 00:00:00", 0.0, None, None, None, None, None)
    assert len(estado) == 2


def test_ingest_insere_novos(db, df_base, escrever_snapshot):
    caminho = escrever_snapshot(df_base)
    stats = ingest_pagamentos(caminho, date(2026, 5, 13), db)

    assert stats["inseridos"] == 3
    n = db.execute("SELECT COUNT(*) FROM _raw_pagamentos").fetchone()[0]
    assert n == 3

def test_guarda_mesmo_ficheiro_salta(db, df_base, escrever_snapshot):
    caminho = escrever_snapshot(df_base)
    ingest_pagamentos(caminho, date(2026, 5, 13), db)            # 1ª vez
    stats = ingest_pagamentos(caminho, date(2026, 5, 13), db)    # 2ª vez, igual

    assert stats.get("saltado") is True

def test_guarda_hash_diferente_levanta_erro(db, df_base, escrever_snapshot):
    p1 = escrever_snapshot(df_base, "snap_a.xlsx")
    ingest_pagamentos(p1, date(2026, 5, 13), db)

    # ficheiro diferente, mas a MESMA snapshot_data → conflito
    df2 = df_base.copy()
    df2.loc[df2["no_parcela"] == 1, "parcelas_valor_liquido"] = 1.0
    p2 = escrever_snapshot(df2, "snap_b.xlsx")

    with pytest.raises(ValueError):
        ingest_pagamentos(p2, date(2026, 5, 13), db)


def test_upsert_anulacao_atualiza_e_loga(db, df_base, escrever_snapshot):
    # snapshot 1: base
    p1 = escrever_snapshot(df_base, "2026-05-13_pagamentos.xlsx")
    ingest_pagamentos(p1, date(2026, 5, 13), db)

    # snapshot 2: anular o pagamento no_parcela 1
    df2 = df_base.copy()
    df2.loc[df2["no_parcela"] == 1, "pag_anulado"] = "Sim"
    df2.loc[df2["no_parcela"] == 1, "pag_data_anulacao"] = pd.Timestamp("2026-03-01")
    p2 = escrever_snapshot(df2, "2026-06-09_pagamentos.xlsx")

    stats = ingest_pagamentos(p2, date(2026, 6, 9), db)

    # 1 linha mudou, 2 ficaram iguais, 2 campos mudaram (anulado + data_anulacao)
    assert stats["atualizados"] == 1
    assert stats["ignorados"] == 2
    assert stats["alteracoes"] == 2

    # o estado na BD reflete a anulação
    row = db.execute(
        "SELECT pag_anulado FROM _raw_pagamentos WHERE no_parcela = 1"
    ).fetchone()
    assert row[0] == "Sim"

    # e o log registou 2 entradas para essa linha
    n_log = db.execute(
        "SELECT COUNT(*) FROM _log_alteracoes WHERE no_parcela = 1"
    ).fetchone()[0]
    assert n_log == 2


def test_upsert_status_utente_atualiza_sem_log(db, df_base, escrever_snapshot):
    # snapshot 1: Ana (utente 100) ativa
    p1 = escrever_snapshot(df_base, "2026-05-13_pagamentos.xlsx")
    ingest_pagamentos(p1, date(2026, 5, 13), db)

    # snapshot 2: a Ana cancelou — o export traz as linhas ANTIGAS dela
    # com o status atual "M" (o software de gestão desnormaliza o estado da
    # sócia em todas as linhas de pagamento)
    df2 = df_base.copy()
    df2.loc[df2["utente_no_insc"] == 100, "utente_status"] = "M"
    p2 = escrever_snapshot(df2, "2026-06-09_pagamentos.xlsx")
    stats = ingest_pagamentos(p2, date(2026, 6, 9), db)

    # a linha foi atualizada, mas SEM auditoria: não é mutação do evento
    # pagamento, é refresco da dimensão utente
    assert stats["atualizados"] == 1
    assert stats["ignorados"] == 2
    assert stats["alteracoes"] == 0

    # o status na BD segue o snapshot mais recente
    status = db.execute(
        "SELECT utente_status FROM _raw_pagamentos WHERE no_parcela = 1"
    ).fetchone()[0]
    assert status == "M"

    n_log = db.execute("SELECT COUNT(*) FROM _log_alteracoes").fetchone()[0]
    assert n_log == 0
