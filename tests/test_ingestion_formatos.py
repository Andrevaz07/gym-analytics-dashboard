"""
Testes dos dois formatos em que o software de gestão exporta o MESMO relatório.

- **Cru**: cabeçalho na linha 0, uma coluna por campo. Foi o que veio a 13-05.
- **Formatado**: 4 linhas de título e janela temporal em cima, cabeçalho na
  linha 4, células fundidas a gerar colunas vazias intercaladas. Foi o que veio
  a 05-08.

O conteúdo é idêntico; muda só a embalagem. `load_acessos` tem de devolver a
mesma coisa nos dois casos, e tem de recusar um relatório que não seja este.
"""
import pandas as pd
import pytest

from src.ingestion import load_acessos, load_pagamentos


# Nomes crus como o software de gestão os escreve — com espaço à frente, quebra de
# linha ao meio e o ordinal 'º'. Usá-los aqui testa também a normalização.
CABECALHO_ACESSOS = [
    " Utente\n Estado", " Utente\n Nº Insc.", " Utente\n Nome",
    " Utente\n Perfil", " Turma\n Nome", " Data", " Hora\n Entrada", " Dia",
]

# Serial do Excel: dias desde 1899-12-30 (a origem que o load_acessos usa).
def _serial(data: str) -> int:
    return (pd.Timestamp(data) - pd.Timestamp("1899-12-30")).days


LINHAS = [
    ["A", 3, "Ana",     "Plano GINÁSIO 25",         "Acesso Instalacoes", _serial("2026-01-05"), 0.698, "Seg"],
    ["A", 4, "Beatriz", "Plano GINÁSIO 25",         "Pilates",            _serial("2026-01-06"), 0.5,   "Ter"],
    ["A", 5, "Carla",   "Plano PACK FAMILIA 25", "Zumba",              _serial("2026-01-07"), 0.75,  "Qua"],
]


def _escrever_formatado(caminho, cabecalho, linhas):
    """
    Grava um .xlsx a imitar o relatório formatado: 4 linhas decorativas em
    cima e uma coluna vazia entre cada duas colunas reais (é isso que as
    células fundidas produzem quando o pandas as lê).
    """
    def intercalar(valores):
        grelha = []
        for v in valores:
            grelha.extend([v, None])
        return grelha

    grelha = [
        [None] * (len(cabecalho) * 2),
        [None, "Histórico geral de acessos"] + [None] * (len(cabecalho) * 2 - 2),
        [None, "[Data] entre 2026-01-01 e 2026-01-31"] + [None] * (len(cabecalho) * 2 - 2),
        [None] * (len(cabecalho) * 2),
        intercalar(cabecalho),
        *[intercalar(linha) for linha in linhas],
    ]
    pd.DataFrame(grelha).to_excel(caminho, index=False, header=False)
    return caminho


def _escrever_cru(caminho, cabecalho, linhas):
    """Grava o mesmo conteúdo no formato cru: cabeçalho na linha 0."""
    pd.DataFrame(linhas, columns=cabecalho).to_excel(caminho, index=False)
    return caminho


def test_le_formato_cru(tmp_path):
    df = load_acessos(_escrever_cru(tmp_path / "cru.xlsx", CABECALHO_ACESSOS, LINHAS))

    assert len(df) == 3
    assert df["data"].min() == pd.Timestamp("2026-01-05")


def test_le_formato_formatado(tmp_path):
    """O que veio a 05-08: título em cima e colunas vazias intercaladas."""
    df = load_acessos(
        _escrever_formatado(tmp_path / "fmt.xlsx", CABECALHO_ACESSOS, LINHAS)
    )

    assert len(df) == 3
    # as colunas vazias das células fundidas não podem sobrar
    assert not any(c.startswith("unnamed") for c in df.columns)
    assert df["data"].min() == pd.Timestamp("2026-01-05")


def test_os_dois_formatos_dao_o_mesmo(tmp_path):
    """A embalagem não pode mudar uma única célula do resultado."""
    cru = load_acessos(_escrever_cru(tmp_path / "cru.xlsx", CABECALHO_ACESSOS, LINHAS))
    fmt = load_acessos(
        _escrever_formatado(tmp_path / "fmt.xlsx", CABECALHO_ACESSOS, LINHAS)
    )

    pd.testing.assert_frame_equal(
        cru.sort_index(axis=1), fmt.sort_index(axis=1), check_categorical=False
    )


def test_recusa_relatorio_errado_de_acessos(tmp_path):
    """Sem as colunas da PK não é o relatório de acessos — tem de rebentar."""
    cabecalho = [" Utente\n Nome", " Data", " Doc.\n NIF"]
    linhas = [["Ana", _serial("2026-01-05"), "123456789"]]

    with pytest.raises(ValueError, match="não parece ser o relatório certo"):
        load_acessos(_escrever_cru(tmp_path / "errado.xlsx", cabecalho, linhas))


def test_recusa_extrato_de_faturacao_como_pagamentos(tmp_path):
    """
    Regressão de 05-08-2026: o ginásio exportou "Histórico dos documentos de
    facturação" (nível documento) em vez do histórico de parcelas. Acerta em
    `doc_nome` e mais nada. O erro tem de nomear o que falta, senão o pipeline
    rebenta mais à frente num astype sem explicação.
    """
    cabecalho = [" Nº Pag.", " Nº Doc.", " Doc. Nome", " Data", " Valor", " Anulado"]
    linhas = [[46603, 456, "Ana", _serial("2026-02-02"), 3.0, "Não"]]

    with pytest.raises(ValueError) as erro:
        load_pagamentos(_escrever_cru(tmp_path / "extrato.xlsx", cabecalho, linhas))

    mensagem = str(erro.value)
    for essencial in ["no_parcela", "inv_familia", "parcelas_disponivel"]:
        assert essencial in mensagem
