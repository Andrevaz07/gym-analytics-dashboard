"""
Carregamento e tipagem dos snapshots do software de gestão.
"""



import pandas as pd
from pathlib import Path
import unicodedata
import re

HERE = Path(__file__).parent

DATA_DIR = HERE.parent / "data" / "snapshots"

DEFAULT_PAGAMENTOS_PATH = DATA_DIR / "2026-05-13_pagamentos.xlsx"
DEFAULT_ACESSOS_PATH = DATA_DIR / "2026-05-13_acessos.xlsx"

# Colunas necessárias para a análise
USECOLS_PAGAMENTOS = [
    # Essenciais
    "pag_no_pag", "pag_data", "pag_anulado", "inv_familia",
    "parcelas_valor_liquido", "parcelas_disponivel", "parcelas_qt",
    "utente_no_insc", "utente_data_insc",
    "utente_status",   # A/M/P/S/D — fonte de verdade snapshot; histórico via pagamentos
    # Úteis
    "inv_descricao", "parcelas_descricao", "parcelas_promocoes",
    "pag_data_anulacao", "no_parcela", "divida_no",
    # Investigar
    "pag_no_socio", "pag_no_insc","doc_nome","utente_gestor","utente_tipo_socio"
]

# Só as que precisam de conversão específica
DTYPE_MAP_PAGAMENTOS = {
    # Categóricas
    "pag_anulado": "category",
    "inv_familia": "category",
    "parcelas_promocoes": "category",
    "inv_descricao": "category",
    "utente_status": "category",
    "utente_gestor":"category",
    "utente_tipo_socio": "category",
    # IDs (Int32 nullable)
    "pag_no_pag": "Int32",
    "utente_no_insc": "Int32",
    "pag_no_socio": "Int32",
    "pag_no_insc": "Int32",
    "divida_no": "Int32",
    # parcelas_qt e no_parcela ficam float64 inferido (defensivo)
}


# Datas com conversação especifica
DATE_COLS_PAGAMENTOS = ["pag_data", "pag_data_anulacao", "utente_data_insc","parcelas_disponivel"]

USECOLS_ACESSOS = [
    # IDs e identificação
    "utente_no_insc", "utente_nome",
    # Estado e plano (self-contained)
    "utente_estado", "utente_perfil",
    # Evento
    "turma_nome", "data", "hora_entrada", "dia",
]

DTYPE_MAP_ACESSOS = {
     # IDs
    "utente_no_insc": "Int32",
    # Texto livre (muitos valores distintos — string, não category)
    "utente_nome": "string",
    # Categóricas (poucos valores distintos)
    "utente_estado": "category",
    "utente_perfil": "category",
    "turma_nome": "category",
    "dia": "category",
}


DATE_COLS_ACESSOS = ["data"]
TIME_COLS_ACESSOS = ["hora_entrada"]

"""
Nomes feios no Excel do software de gestão que precisam de ser normalizados:
- Pag. N° Pag,
- Inv. Família
É necessário uma função para retirar acentos e converter para snake_case
"""
def retira_acentos(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def _normalize_column_name(name: str) -> str:
    """Converte um nome de coluna para snake_case."""
    s = name.strip().lower()
    s = retira_acentos(s)
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = s.strip("_")
    return s


# Quantas linhas espreitar à procura do cabeçalho. Os relatórios formatados
# do software de gestão gastam 4 linhas em título e janela temporal antes da tabela;
# 10 dá folga sem custar nada.
MAX_LINHAS_CABECALHO = 10

# Colunas que IDENTIFICAM o relatório. Sem elas o ficheiro é outro relatório,
# não uma variante de formato do mesmo — e mais vale recusar do que ingerir
# lixo. A 05-08-2026 o ginásio exportou "Histórico dos documentos de
# facturação" (nível documento) em vez do histórico de parcelas: acertava em
# `doc_nome` e mais nada, e sem esta guarda passaria a deteção.
COLUNAS_ESSENCIAIS_PAGAMENTOS = [
    "no_parcela",              # chave primária de _raw_pagamentos
    "inv_familia",             # define quem conta como sócia ativa
    "parcelas_disponivel",     # eixo temporal (mês de serviço)
    "parcelas_valor_liquido",  # base do MRR
    "utente_status",
    "utente_no_insc",
]

COLUNAS_ESSENCIAIS_ACESSOS = [
    "utente_no_insc", "data", "hora_entrada",  # a PK de _raw_presencas
    "turma_nome",
]


def _detetar_linha_cabecalho(
    path: Path, usecols: list[str], essenciais: list[str]
) -> int:
    """
    Descobre em que linha do ficheiro está o cabeçalho real e confirma que o
    relatório é o certo.

    O software de gestão exporta o mesmo relatório de duas maneiras: **cru** (cabeçalho
    na linha 0, uma coluna por campo) ou **formatado** (título e janela temporal
    em cima, cabeçalho na linha 4, células fundidas a gerar colunas vazias
    intercaladas). Em vez de fixar o número, procuramos a linha que reconhece
    mais nomes esperados — funciona nos dois formatos e em variantes futuras.

    Levanta ValueError se faltar alguma coluna essencial, nomeando-a. Falhar
    alto aqui é muito melhor do que rebentar mais à frente num astype obscuro.
    """
    espreita = pd.read_excel(
        path, engine="openpyxl", header=None, nrows=MAX_LINHAS_CABECALHO
    )

    esperadas = set(usecols)
    melhor_linha, melhor_nomes, melhor_contagem = 0, set(), 0

    for i in range(len(espreita)):
        nomes = {
            _normalize_column_name(str(valor))
            for valor in espreita.iloc[i]
            if pd.notna(valor)
        }
        contagem = len(nomes & esperadas)
        if contagem > melhor_contagem:
            melhor_linha, melhor_nomes, melhor_contagem = i, nomes, contagem

    em_falta = [c for c in essenciais if c not in melhor_nomes]
    if em_falta:
        raise ValueError(
            f"'{path.name}' não parece ser o relatório certo do software de gestão.\n"
            f"Faltam colunas essenciais: {em_falta}\n"
            f"Melhor cabeçalho encontrado: linha {melhor_linha} "
            f"({melhor_contagem} colunas reconhecidas de {len(esperadas)})."
        )

    return melhor_linha

def load_pagamentos(path: Path = DEFAULT_PAGAMENTOS_PATH) -> pd.DataFrame:
    """
    Carrega o snapshot de pagamentos do software de gestão com tipagem aplicada.

    Lê só as colunas em USECOLS, normaliza os nomes para snake_case,
    aplica ps dtypes do DTYPE_MAP. Datas em serial Excel pendentes.
    """
    df = pd.read_excel(
        path,
        engine="openpyxl",
        header=_detetar_linha_cabecalho(
            path, USECOLS_PAGAMENTOS, COLUNAS_ESSENCIAIS_PAGAMENTOS
        ),
        usecols=lambda col: _normalize_column_name(col) in USECOLS_PAGAMENTOS,
        na_values=["-"]
         )

    df.columns = [_normalize_column_name(c) for c in df.columns]

    df = df.astype(DTYPE_MAP_PAGAMENTOS)

    for col in DATE_COLS_PAGAMENTOS:
        if pd.api.types.is_numeric_dtype(df[col]):
            col_num = pd.to_numeric(df[col],errors="coerce")
            df[col] = pd.to_datetime(col_num,
                origin= "1899-12-30",
                unit="D",
                errors="coerce"
            )
        #se já for datetime, não mexer

        #Uniformizar precisão no fim 
        df[col] = df[col].astype("datetime64[s]")
    
    return df


def load_acessos(path: Path = DEFAULT_ACESSOS_PATH) -> pd.DataFrame:

    """
    Carrega o snapshot de acessos do software de gestão com tipagem aplicada.

    Lê só as colunas em USECOLS, normaliza os nomes para snake_case,
    aplica ps dtypes do DTYPE_MAP. Datas em serial Excel pendentes.
    """
    df = pd.read_excel(
        path,
        engine="openpyxl",
        header=_detetar_linha_cabecalho(
            path, USECOLS_ACESSOS, COLUNAS_ESSENCIAIS_ACESSOS
        ),
        usecols=lambda col: _normalize_column_name(col) in USECOLS_ACESSOS,
        na_values=["-"]
         )

    df.columns = [_normalize_column_name(c) for c in df.columns]

    df = df.dropna(subset=["utente_no_insc"]).reset_index(drop=True)
    
    df = df.astype(DTYPE_MAP_ACESSOS)

    for col in TIME_COLS_ACESSOS:
        df[col] = pd.to_timedelta(df[col], unit= "D", errors="coerce")

        df[col] = df[col].astype("timedelta64[ns]")

    for col in DATE_COLS_ACESSOS:
        if pd.api.types.is_numeric_dtype(df[col]):
            col_num = pd.to_numeric(df[col],errors="coerce")
            df[col] = pd.to_datetime(col_num,
                origin= "1899-12-30",
                unit="D",
                errors="coerce"
            )
        #se já for datetime, não mexer

        #Uniformizar precisão no fim 
        df[col] = df[col].astype("datetime64[s]")
    
    return df
