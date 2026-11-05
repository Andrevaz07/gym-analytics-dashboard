"""
Testes da receita por área e por plano (`src.receita`).

A regra que não pode falhar: o total de um período é o que o cartão
Faturação mostra nesses meses. Se não bater, a gerente vê dois números para
a mesma pergunta.
"""
import pandas as pd
import pytest

from src.kpis import faturacao_total_no_mes
from src.receita import OUTROS, TAXAS, detalhe, por_area, receita_mensal


def _linha(familia, descricao, valor, mes="2026-03", anulado="Não"):
    return {
        "inv_familia": familia,
        "inv_descricao": descricao,
        "parcelas_valor_liquido": valor,
        "parcelas_disponivel": pd.Timestamp(f"{mes}-01"),
        "pag_anulado": anulado,
    }


@pytest.fixture
def pagamentos():
    return pd.DataFrame([
        _linha("Mensalidades", "Mensalidade Base 25", 50),
        _linha("Mensalidades", "Mensalidade Base 25", 50),
        _linha("Mensalidades", "Mensalidade Base", 35),
        _linha("Mensalidades", "Plano Pack familia 25", 40),
        _linha("Mensalidades", "Pack familia", 30),
        _linha("Mensalidades", "Mensalidade Online25", 20),
        _linha("Mensalidades", "Taxa de Congelamento", 10),
        _linha("Mensalidades", "Multa atraso mensalidade", 5),
        _linha("Personal Trainer", "Personal Shopper", 100),
        _linha("Personal Trainer", "Personal Shopper 2", 200),
        _linha("Nutrição", "Consulta", 40),
        _linha("Prozis", "Barra proteica", 3),
        _linha("Loja", "Garrafa", 7),
        _linha("cacifos", "Cacifo mensal", 12),
        _linha("cacifos", "Cacifo mensal", 6),
        _linha("Cacifos", "Cacifo anual", 8),
        _linha("Massagens", "Massagem 30 min", 25),
        # Fora das contas: anulada, e meses fora do período.
        _linha("Mensalidades", "Mensalidade Base 25", 999, anulado="Sim"),
        _linha("Mensalidades", "Mensalidade Base 25", 500, mes="2026-02"),
        _linha("Mensalidades", "Mensalidade Base 25", 500, mes="2026-04"),
    ])


@pytest.fixture
def mensal(pagamentos):
    return receita_mensal(pagamentos)


def test_total_do_mes_e_o_do_cartao_faturacao(pagamentos, mensal):
    for mes in ["2026-02", "2026-03", "2026-04"]:
        total = por_area(mensal, mes, mes)["euros"].sum()
        assert total == pytest.approx(
            faturacao_total_no_mes(pagamentos, pd.Period(mes, "M"))
        )


def test_periodo_inclui_os_dois_meses_das_pontas(mensal):
    assert por_area(mensal, "2026-02", "2026-04")["euros"].sum() == pytest.approx(
        641 + 500 + 500
    )


def test_percentagens_somam_cem(mensal):
    assert por_area(mensal, "2026-03", "2026-03")["pct"].sum() == pytest.approx(100)


def test_outros_fica_no_fim_mesmo_com_mais_receita(mensal):
    areas = por_area(mensal, "2026-03", "2026-03")["area"].tolist()
    assert areas[0] == "Personal Trainer"
    assert areas[-1] == OUTROS


def test_versoes_de_tarifa_juntam_se_no_mesmo_plano(mensal):
    planos = detalhe(mensal, "Mensalidades", "2026-03", "2026-03").set_index("item")
    assert planos.loc["Mensalidade Base", "euros"] == 135
    assert planos.loc["Mensalidade Online", "euros"] == 20


def test_mesmo_plano_com_e_sem_prefixo_fica_com_o_nome_mais_comum(mensal):
    planos = detalhe(mensal, "Mensalidades", "2026-03", "2026-03")["item"].tolist()
    assert "Plano Pack familia" in planos
    assert "Pack familia" not in planos


def test_taxas_multas_e_acertos_numa_linha(mensal):
    planos = detalhe(mensal, "Mensalidades", "2026-03", "2026-03").set_index("item")
    assert planos.loc[TAXAS, "euros"] == 15


def test_so_o_25_e_versao_de_tarifa(mensal):
    """'Personal Shopper 2' é outro produto, com outro preço."""
    planos = detalhe(mensal, "Personal Trainer", "2026-03", "2026-03")["item"]
    assert set(planos) == {"Personal Shopper", "Personal Shopper 2"}


def test_loja_junta_as_marcas_e_o_detalhe_e_por_marca(mensal):
    loja = detalhe(mensal, "Loja e bar", "2026-03", "2026-03").set_index("item")
    assert set(loja.index) == {"Prozis", "Loja"}
    assert loja["euros"].sum() == 10


def test_familia_desconhecida_vai_para_outros_a_vista(mensal):
    """Um serviço novo não pode cair no meio dos produtos da loja."""
    outros = detalhe(mensal, OUTROS, "2026-03", "2026-03")["item"].tolist()
    assert "Massagens" in outros


def test_familia_com_maiusculas_diferentes_fica_numa_linha(mensal):
    """A base real escreve "cacifos"; a de demonstração, "Cacifos"."""
    outros = detalhe(mensal, OUTROS, "2026-03", "2026-03").set_index("item")
    assert outros.loc["cacifos", "euros"] == 12 + 6 + 8
    assert "Cacifos" not in outros.index


def test_percentagens_do_detalhe(mensal):
    planos = detalhe(mensal, "Personal Trainer", "2026-03", "2026-03").set_index("item")
    assert planos.loc["Personal Shopper 2", "pct_area"] == pytest.approx(200 / 300 * 100)
    assert planos.loc["Personal Shopper 2", "pct_total"] == pytest.approx(200 / 641 * 100)
