"""
Testes de src.socias — quem é sócia AGORA.

Cada teste aqui corresponde a um erro que existiu de facto na BD real.
Os números do docstring de cada um são os que se mediram em 2026-09-07,
sobre o snapshot de Julho.
"""

import pandas as pd
import pytest

from src.socias import (
    ESTADOS_SOCIA,
    ids_com_presenca_esperada,
    ids_socias,
    socias_atuais,
)

MAIO = "2026-05-13"
JULHO = "2026-07-31"


def _linha(conn, no_parcela, utente, *, status, snapshot, pag_data, servico=None):
    """Uma linha em _raw_pagamentos. Só se indica o que interessa ao teste."""
    conn.execute(
        """INSERT INTO _raw_pagamentos
           (no_parcela, utente_no_insc, utente_status, atualizado_em_snapshot,
            pag_data, parcelas_disponivel, inv_familia, pag_anulado,
            parcelas_valor_liquido)
           VALUES (?,?,?,?,?,?,'Mensalidades','Não',47.97)""",
        (no_parcela, utente, status, snapshot, pag_data, servico or pag_data),
    )


def _cobertura(conn, snapshot, de, ate):
    conn.execute(
        """INSERT INTO _raw_snapshots
           (snapshot_data, tabela, ficheiro_origem, hash_ficheiro, n_linhas,
            cobertura_de, cobertura_ate)
           VALUES (?, 'pagamentos', 'teste', '-', 1, ?, ?)""",
        (snapshot, de, ate),
    )


@pytest.fixture
def bd(db):
    """
    Duas extrações, como na realidade: a de Maio trouxe o histórico todo,
    a de Julho só a janela de seis meses.
    """
    _cobertura(db, MAIO, "2011-10-02", "2026-05-13")
    _cobertura(db, JULHO, "2026-01-28", "2026-07-31")
    return db


def test_estado_vem_da_extracao_mais_recente(bd):
    """
    Uma sócia que cancelou tem linhas antigas a dizer "A" (nunca mais
    reescritas, porque caem fora da janela de 6 meses) e linhas recentes a
    dizer "M". Vale a mais recente.

    Sem isto, "tem alguma linha A?" respondia "já alguma vez foi activa" —
    só podia crescer, e dava 448 sócias quando eram 380.
    """
    _linha(bd, 1, 100, status="A", snapshot=MAIO, pag_data="2025-06-10")
    _linha(bd, 2, 100, status="M", snapshot=JULHO, pag_data="2026-03-10")

    assert socias_atuais(bd).loc[100, "estado"] == "M"
    assert 100 not in ids_socias(socias_atuais(bd))


def test_linha_de_mes_futuro_nao_manda_no_estado(bd):
    """
    Regressão do caso que motivou o módulo. A sócia tem uma avaliação de
    Julho a €0 lançada pela extração de MAIO, e mensalidades até Maio
    reescritas pela de Julho com o estado "M".

    Ordenar por `parcelas_disponivel` escolheria a linha de Julho — que é
    a mais recente em mês de serviço, mas traz o estado velho — e dava a
    sócia como activa depois de ela ter cancelado.
    """
    _linha(bd, 1, 200, status="M", snapshot=JULHO,
           pag_data="2026-05-02", servico="2026-05-01")
    _linha(bd, 2, 200, status="A", snapshot=MAIO,
           pag_data="2026-05-10", servico="2026-07-01")   # pré-lançada

    assert socias_atuais(bd).loc[200, "estado"] == "M"


def test_suspensa_continua_a_ser_socia(bd):
    """
    S = suspendeu a mensalidade por um período prolongado mas mantém o
    vínculo, para não pagar inscrição outra vez ao voltar. Não é uma
    saída.
    """
    _linha(bd, 1, 300, status="S", snapshot=JULHO, pag_data="2026-07-10")
    assert 300 in ids_socias(socias_atuais(bd))
    assert "S" in ESTADOS_SOCIA


def test_suspensa_fica_fora_da_lista_de_risco(bd):
    """
    O único sítio onde A e S se separam: a ausência da suspensa é
    combinada, portanto sinalizá-la como "não vem há 60 dias" faria
    telefonar a quem já avisou que ia estar fora.
    """
    _linha(bd, 1, 300, status="S", snapshot=JULHO, pag_data="2026-07-10")
    _linha(bd, 2, 301, status="A", snapshot=JULHO, pag_data="2026-07-10")

    esperadas = ids_com_presenca_esperada(socias_atuais(bd))
    assert 301 in esperadas
    assert 300 not in esperadas


@pytest.mark.parametrize("estado", ["M", "P", "D"])
def test_estados_que_nao_sao_socia(bd, estado):
    """M = ex-sócia, D = dívida em litígio, P = indefinido. Nenhum conta."""
    _linha(bd, 1, 400, status=estado, snapshot=JULHO, pag_data="2026-07-10")
    assert 400 not in ids_socias(socias_atuais(bd))


def test_quem_nao_veio_na_ultima_extracao_nao_conta(bd):
    """
    O estado só vale se a extração mais recente falou dela. Doze sócias
    reais estavam marcadas "A" sem pagar nada desde Junho de 2022: a
    fonte nunca mais as mencionou e o "A" ficou fossilizado.
    """
    _linha(bd, 1, 500, status="A", snapshot=MAIO, pag_data="2022-06-15")

    s = socias_atuais(bd)
    assert s.loc[500, "estado"] == "A"
    assert not s.loc[500, "veio_na_ultima_extracao"]
    assert 500 not in ids_socias(s)


def test_sem_cobertura_registada_ninguem_e_excluido(bd):
    """
    Sem saber a janela da última extração não se inventa uma exclusão —
    seria pior errar a esconder sócias reais.
    """
    bd.execute("DELETE FROM _raw_snapshots")
    _linha(bd, 1, 600, status="A", snapshot=MAIO, pag_data="2022-06-15")

    assert 600 in ids_socias(socias_atuais(bd))


def test_bd_vazia_devolve_tabela_vazia(db):
    assert socias_atuais(db).empty
    assert ids_socias(socias_atuais(db)) == set()
