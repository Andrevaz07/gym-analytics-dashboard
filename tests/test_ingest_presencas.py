from datetime import date
import pandas as pd
from src.ingest_presencas import ingest_presencas


def test_insere_acessos(db, df_base_acessos, escrever_snapshot):
    p = escrever_snapshot(df_base_acessos, "acessos.xlsx")
    stats = ingest_presencas(p, date(2026, 5, 13), db)

    assert stats["inseridos"] == 3
    n = db.execute("SELECT COUNT(*) FROM _raw_presencas").fetchone()[0]
    assert n == 3


def test_dedup_insert_or_ignore(db, df_base_acessos, escrever_snapshot):
    p = escrever_snapshot(df_base_acessos, "acessos.xlsx")
    ingest_presencas(p, date(2026, 5, 13), db)          # 1ª vez: insere 3
    stats = ingest_presencas(p, date(2026, 6, 9), db)   # 2ª vez, data diferente

    # as 3 linhas já existem por PK → ignoradas em silêncio
    assert stats["inseridos"] == 0
    assert stats["ignorados"] == 3


def test_guarda_mesmo_ficheiro_salta(db, df_base_acessos, escrever_snapshot):
    p = escrever_snapshot(df_base_acessos, "acessos.xlsx")
    ingest_presencas(p, date(2026, 5, 13), db)
    stats = ingest_presencas(p, date(2026, 5, 13), db)  # mesmo ficheiro + data

    assert stats.get("saltado") is True


def test_utente_no_insc_guardado_como_integer(db, df_base_acessos, escrever_snapshot):
    # blindagem do bug de hoje: nunca mais aceitar BLOB
    p = escrever_snapshot(df_base_acessos, "acessos.xlsx")
    ingest_presencas(p, date(2026, 5, 13), db)

    tipos = db.execute(
        "SELECT DISTINCT typeof(utente_no_insc) FROM _raw_presencas"
    ).fetchall()
    assert tipos == [("integer",)]


def test_ignora_registos_com_pk_nula(db, df_base_acessos, escrever_snapshot):
    # Adicionar uma linha com utente nulo e outra com data nula e outra com hora nula
    df_mau = df_base_acessos.copy()
    
    novas_linhas = pd.DataFrame([
        {"utente_no_insc": pd.NA, "data": pd.Timestamp("2026-05-13"), "hora_entrada": pd.Timedelta(hours=9), "utente_nome": "Mau 1"},
        {"utente_no_insc": 9999, "data": pd.NaT, "hora_entrada": pd.Timedelta(hours=9), "utente_nome": "Mau 2"},
        {"utente_no_insc": 8888, "data": pd.Timestamp("2026-05-13"), "hora_entrada": pd.NaT, "utente_nome": "Mau 3"},
    ])
    df_mau = pd.concat([df_mau, novas_linhas], ignore_index=True)
    
    p = escrever_snapshot(df_mau, "acessos_mau.xlsx")
    stats = ingest_presencas(p, date(2026, 5, 13), db)
    
    # As 3 linhas originais entram, as 3 com PK nula são descartadas
    assert stats["inseridos"] == 3
    n = db.execute("SELECT COUNT(*) FROM _raw_presencas").fetchone()[0]
    assert n == 3


def test_hora_entrada_formatada_corretamente_com_nas(db, df_base_acessos, escrever_snapshot):
    # Bug regressão: NaNs corrompiam a coluna inteira para float, criando strings "8.0:5.0:0.0"
    df_misto = df_base_acessos.copy()
    
    linha_com_nan = pd.DataFrame([
        {"utente_no_insc": 7777, "data": pd.Timestamp("2026-05-13"), "hora_entrada": pd.NaT, "utente_nome": "Tem NaN"}
    ])
    df_misto = pd.concat([df_misto, linha_com_nan], ignore_index=True)
    
    p = escrever_snapshot(df_misto, "acessos_misto.xlsx")
    ingest_presencas(p, date(2026, 5, 13), db)
    
    horas_na_bd = db.execute("SELECT hora_entrada FROM _raw_presencas").fetchall()
    
    # A linha NaT foi ignorada. As restantes devem ter formatação "HH:MM:SS" (len 8, sem '.')
    for (hora_bd,) in horas_na_bd:
        assert len(hora_bd) == 8
        assert "." not in hora_bd
