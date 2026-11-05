"""
Fixtures partilhadas pelos testes de ingestão.

Fornece:
- df_base: um DataFrame pequeno (3 linhas) com TODAS as colunas que o
  load_pagamentos espera ler, todas válidas e pag_anulado='Não'.
- escrever_snapshot: fábrica que grava um df como .xlsx em tmp_path e
  devolve o caminho, pronto a passar ao ingest_pagamentos.

A fábrica existe porque construir à mão um Excel que sobreviva ao
pipeline (load -> clean -> 17 colunas do schema) é trabalho de andaime;
os testes focam-se na lógica, não em montar colunas.
"""
import pandas as pd
import pytest

from src.db import conectar, criar_schema


@pytest.fixture
def db(tmp_path):
    """BD temporária e vazia, criada de fresco para cada teste que a pedir."""
    conn = conectar(tmp_path / "teste.sqlite")
    criar_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def df_base_acessos() -> pd.DataFrame:
    """
    3 acessos válidos, com os nomes de coluna crus que o load_acessos espera.
    hora_entrada vai como fração de dia (formato nativo do Excel): 0.5 = meio-dia.
    """
    return pd.DataFrame(
        {
            "utente_no_insc": [3, 4, 5],
            "utente_nome": ["Ana", "Beatriz", "Carla"],
            "utente_estado": ["A", "A", "A"],
            "utente_perfil": ["Plano GINÁSIO 25", "Plano GINÁSIO 25", "Plano PACK FAMILIA 25"],
            "turma_nome": ["Acesso Instalacoes", "Pilates", "Zumba"],
            "data": pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"]),
            "hora_entrada": [0.698, 0.5, 0.75],
            "dia": ["Seg", "Ter", "Qua"],
        }
    )


@pytest.fixture
def df_base() -> pd.DataFrame:
    """3 pagamentos válidos, não anulados. no_parcela 1/2/3."""
    return pd.DataFrame(
        {
            # chave + identificadores
            "no_parcela": [1, 2, 3],
            "pag_no_pag": [10, 20, 30],
            "pag_no_socio": [100, 200, 300],
            "pag_no_insc": [100, 200, 300],
            "divida_no": [0, 0, 0],
            "utente_no_insc": [100, 200, 300],
            # datas
            "pag_data": pd.to_datetime(["2026-01-10", "2026-01-15", "2026-02-01"]),
            "pag_data_anulacao": pd.to_datetime([None, None, None]),
            "parcelas_disponivel": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-02-01"]),
            "utente_data_insc": pd.to_datetime(["2025-12-01", "2025-12-05", "2026-01-20"]),
            # mutáveis / valores
            "pag_anulado": ["Não", "Não", "Não"],
            "parcelas_valor_liquido": [39.9, 39.9, 25.0],
            # texto / categóricas
            "parcelas_descricao": ["Mensalidade", "Mensalidade", "PT"],
            "parcelas_promocoes": ["Nenhuma", "Nenhuma", "Nenhuma"],
            "inv_familia": ["Mensalidades", "Mensalidades", "PT"],
            "inv_descricao": ["Plano Mensal", "Plano Mensal", "Personal"],
            "utente_status": ["A", "A", "A"],
            "doc_nome": ["Ana", "Beatriz", "Carla"],
            "utente_gestor": ["G1", "G1", "G2"],
            "utente_tipo_socio": ["Normal", "Normal", "Normal"],
        }
    )


@pytest.fixture
def escrever_snapshot(tmp_path):
    """Fábrica: grava um df como .xlsx em tmp_path e devolve o Path."""
    def _escrever(df: pd.DataFrame, nome: str = "2026-05-13_pagamentos.xlsx"):
        caminho = tmp_path / nome
        df.to_excel(caminho, index=False)
        return caminho
    return _escrever
