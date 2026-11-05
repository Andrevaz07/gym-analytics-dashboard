"""
Testes do KPI socias_em_risco (cruza presenças x pagamentos).

Em vez de passar pela ingestão, inserimos linhas cruas direto na BD —
o objetivo é testar a LÓGICA do KPI, não a ingestão (que tem testes próprios).
Cada sócia do cenário foi desenhada para exercer um comportamento.

Âncora do cenário = 2026-04-30 (presença mais recente inserida).
"""
import pytest
from src.presencas_kpis import socias_em_risco

ANCORA = "2026-04-30"


def _pag(conn, utente, *, familia="Mensalidades", descricao="Plano Mensal",
         status="A", anulado="Não", data_insc="2025-06-01"):
    """Insere um pagamento. no_parcela é gerado único."""
    npar = conn.execute(
        "SELECT COALESCE(MAX(no_parcela), 0) + 1 FROM _raw_pagamentos"
    ).fetchone()[0]
    conn.execute(
        """INSERT INTO _raw_pagamentos
           (no_parcela, utente_no_insc, utente_status, inv_familia, inv_descricao,
            pag_anulado, utente_data_insc, atualizado_em_snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (npar, utente, status, familia, descricao, anulado, data_insc, ANCORA),
    )


def _pres(conn, utente, data):
    """Insere uma presença (entrada no ginásio) numa data."""
    conn.execute(
        """INSERT INTO _raw_presencas
           (utente_no_insc, data, hora_entrada, ingerido_em_snapshot)
           VALUES (?, ?, ?, ?)""",
        (utente, data, "10:00:00", ANCORA),
    )


@pytest.fixture
def lista(db):
    """Povoa a BD com um cenário completo e devolve a lista de risco."""
    # 1 — ativa recente: veio no último dia (define a âncora) -> excluída (<30d)
    _pag(db, 1); _pres(db, 1, "2026-04-30")
    # 2 — perdida: última presença há ~104 dias
    _pag(db, 2); _pres(db, 2, "2026-01-16")
    # 3 — 20 dias sem vir: abaixo do corte de 30 -> fora da lista
    _pag(db, 3); _pres(db, 3, "2026-04-10")
    # 4 — veterana sem presença nenhuma (sócia desde 2025)
    _pag(db, 4)
    # 5 — só PT, sem Mensalidade -> fora da população
    _pag(db, 5, familia="Personal Trainer")
    # 6 — Mensalidade Online -> fora da população (não vem fisicamente)
    _pag(db, 6, descricao="Mensalidade Online")
    # 7 — Mensalidade + PT, sem presença -> incluída mas tem_PT=True
    _pag(db, 7); _pag(db, 7, familia="Personal Trainer")
    # 8 — nova sem oportunidade: inscrita a 25-Abr (< 30d antes do fim dos dados)
    _pag(db, 8, data_insc="2026-04-25")
    db.commit()
    return socias_em_risco(db)


def _flag(lista, utente):
    return lista.set_index("utente_no_insc").loc[utente, "flag"]


def test_ancora_nos_dados_nao_no_relogio(lista):
    # sócia 2 veio a 16-Jan; âncora=30-Abr -> 104 dias (não conta de hoje)
    assert lista.set_index("utente_no_insc").loc[2, "dias_ausente"] == 104


def test_um_corte_so_aos_30_dias(lista):
    """
    Medido nos dados do ginásio: 30-59 e 60+ dias saem ao mesmo ritmo
    (~30%), e 14-29 abaixo da média. Ver socias_em_risco.
    """
    assert _flag(lista, 2) == "risco"     # ~104 dias — antes "perdida"
    assert 3 not in lista["utente_no_insc"].values   # 20 dias — antes "atenção"
    assert set(lista["flag"]) <= {"risco", "sem presença no periodo"}


def test_corte_e_configuravel(db, lista):
    """Se a gerência quiser outro limite, é um argumento — não código."""
    assert _flag(socias_em_risco(db, dias=14), 3) == "risco"


def test_veterana_sem_presenca_incluida(lista):
    linha = lista[lista["utente_no_insc"] == 4]
    assert len(linha) == 1
    assert linha["flag"].iloc[0] == "sem presença no periodo"
    assert bool(linha["tem_PT"].iloc[0]) is False


def test_ativa_recente_excluida(lista):
    # veio há 0 dias (<30) -> não é risco
    assert 1 not in lista["utente_no_insc"].values


def test_pt_puro_fora_da_populacao(lista):
    # sem Mensalidade -> nem entra
    assert 5 not in lista["utente_no_insc"].values


def test_mensalidade_online_excluida(lista):
    assert 6 not in lista["utente_no_insc"].values


def test_tem_pt_marcado(lista):
    linha = lista[lista["utente_no_insc"] == 7]
    assert len(linha) == 1
    assert bool(linha["tem_PT"].iloc[0]) is True


def test_nova_sem_oportunidade_excluida(lista):
    # sem presença, mas inscrita tarde demais para ter tido oportunidade
    assert 8 not in lista["utente_no_insc"].values
