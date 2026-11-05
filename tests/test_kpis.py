import pandas as pd
import pytest

from src.kpis import (
    socias_ativas_no_mes,
    n_socias_ativas_no_mes,
    mrr_no_mes,
    faturacao_total_no_mes,
    arpu_no_mes,
    socios_perdidos_no_mes,
    novos_socios_no_mes,
    taxa_churn,
    taxa_retencao,
    ltv_estimado,
)


JAN = pd.Period("2026-01","M")
FEV = pd.Period("2026-02","M")

def _linha(utente, mes, *, familia="Mensalidades", valor=30.0, anulado="Não", status="A"):
    """ Uma linha de pagamento.Só indica o que foge ao normal."""
    return {
        "utente_no_insc": utente,
        "parcelas_disponivel": pd.Timestamp(str(mes) + "-01"),
        "pag_anulado": anulado,
        "inv_familia": familia,
        "parcelas_valor_liquido": valor,
        "utente_status": status,
    }



@pytest.fixture
def df():
    """ Cenário: cada sócia exerce uma regra(ver comentarios)."""
    return pd.DataFrame([
        #1 - baseline: mensalidade em Jan e Fev, -> ativa nos 2 meses
        _linha(1, JAN),
        _linha(1,FEV),
        #2- só Jan, status D -> perdida em Fev, e "não activa" no snapshot
        _linha(2,JAN,status="D"),
        #3- ativa via pack
        _linha(3,JAN, familia= "Avaliações"),
        _linha(3,JAN, familia= "Nutrição"),
        #4- Morta via Pack incompleto
        _linha(4,JAN, familia= "Avaliações"),
        #5- Nova em Fev
        _linha(5,FEV),
        #6 - Anulada
        _linha(6,JAN, anulado="Sim"),
        #7- Fora do MRR
        _linha(7,JAN,familia="Loja")
    ])


def test_ativa_por_plano_principal(df):
    assert 1 in socias_ativas_no_mes(df, JAN)


def test_ativa_via_pack_completo(df):
    # Avaliações + Nutrição no mesmo mês formam um pack autónomo
    assert 3 in socias_ativas_no_mes(df, JAN)


def test_pack_incompleto_nao_conta(df):
    # só Avaliações, sem Nutrição -> não é ativa
    assert 4 not in socias_ativas_no_mes(df, JAN)


def test_anulada_excluida(df):
    assert 6 not in socias_ativas_no_mes(df, JAN)


def test_loja_nao_e_ativa(df):
    assert 7 not in socias_ativas_no_mes(df, JAN)


def test_fecho_ativas_jan(df):
    # set exato: apanha inclusões acidentais que os testes de pertença deixam passar
    assert socias_ativas_no_mes(df, JAN) == {1, 2, 3}


def test_fecho_ativas_fev(df):
    # em Fev só a sócia 1 (continua) e a 5 (nova) têm mensalidade
    assert socias_ativas_no_mes(df, FEV) == {1, 5}


# ---------------------------------------------------------------------------
# O "agora" mudou-se para src/socias.py — ver tests/test_socias.py.
# Não cabia aqui: além do estado mais recente de cada sócia, precisa de
# saber quem veio na última extração, e isso vive em _raw_snapshots.
# ---------------------------------------------------------------------------

def test_contagens_sao_o_tamanho_dos_conjuntos(df):
    # as funções n_* não têm lógica própria — um sanity check chega
    assert n_socias_ativas_no_mes(df, JAN) == 3


# ---------------------------------------------------------------------------
# Receita — MRR (recorrente) vs faturação total (caixa)
# ---------------------------------------------------------------------------

def test_mrr_jan(df):
    # Linhas de JAN, não anuladas, com família em FAMILIAS_MRR:
    #   sócia 1 Mensalidades .. 30
    #   sócia 2 Mensalidades .. 30
    #   sócia 3 Avaliações ... 30
    #   sócia 3 Nutrição ..... 30
    #   sócia 4 Avaliações ... 30
    # = 150. Fora: sócia 6 (anulada) e sócia 7 (Loja não é família MRR).
    assert mrr_no_mes(df, JAN) == pytest.approx(150.0)


def test_faturacao_inclui_familias_fora_do_mrr(df):
    # mesma conta sem o filtro de família -> entra a Loja: 150 + 30 = 180
    assert faturacao_total_no_mes(df, JAN) == pytest.approx(180.0)


def test_diferenca_entre_faturacao_e_mrr_e_a_receita_nao_recorrente(df):
    # o que separa os dois KPIs é exatamente a linha da Loja
    diferenca = faturacao_total_no_mes(df, JAN) - mrr_no_mes(df, JAN)
    assert diferenca == pytest.approx(30.0)


def test_anulada_nao_conta_para_receita(df):
    # A sócia 6 tem 30€ em JAN, anulados. Para provar que é a anulação que a
    # exclui (e não outra coisa qualquer), corremos o mesmo cenário com o
    # pagamento dela válido: a faturação sobe exatamente 30€.
    com_pagamento_valido = df.copy()
    com_pagamento_valido.loc[
        com_pagamento_valido["utente_no_insc"] == 6, "pag_anulado"
    ] = "Não"

    assert faturacao_total_no_mes(df, JAN) == pytest.approx(180.0)
    assert faturacao_total_no_mes(com_pagamento_valido, JAN) == pytest.approx(210.0)


# ---------------------------------------------------------------------------
# ARPU — receita média por sócia ativa
# ---------------------------------------------------------------------------

def test_arpu_jan(df):
    # MRR 150 / 3 ativas ({1, 2, 3}) = 50
    assert arpu_no_mes(df, JAN) == pytest.approx(50.0)


def test_arpu_inflacionado_por_receita_de_quem_nao_e_ativa(df):
    # Assimetria de definição: os 30€ de Avaliações da sócia 4 entram no
    # MRR (Avaliações ∈ FAMILIAS_MRR), mas ela NÃO conta como ativa (pack
    # incompleto). Receita no numerador, sócia fora do denominador.
    # Este teste documenta o comportamento atual — a definição está por
    # validar com a gerente, não é um bug do código.
    sem_socia_4 = df[df["utente_no_insc"] != 4]
    assert arpu_no_mes(df, JAN) == pytest.approx(50.0)           # 150 / 3
    assert arpu_no_mes(sem_socia_4, JAN) == pytest.approx(40.0)  # 120 / 3


def test_arpu_sem_ativas_devolve_zero(df):
    # guarda contra divisão por zero — mês sem dados nenhuns
    assert arpu_no_mes(df, pd.Period("2026-06", "M")) == 0.0


# ---------------------------------------------------------------------------
# Fluxo — quem entrou e quem saiu
# ---------------------------------------------------------------------------

def test_perdidas_fev(df):
    # ativas(JAN) {1, 2, 3} - ativas(FEV) {1, 5} = {2, 3}
    assert socios_perdidos_no_mes(df, FEV) == {2, 3}


def test_novas_fev(df):
    # ativas(FEV) {1, 5} - ativas(JAN) {1, 2, 3} = {5}
    assert novos_socios_no_mes(df, FEV) == {5}


def test_socia_que_fica_nao_aparece_em_nenhum_dos_fluxos(df):
    # a sócia 1 está ativa nos dois meses: não é perdida nem nova
    assert 1 not in socios_perdidos_no_mes(df, FEV)
    assert 1 not in novos_socios_no_mes(df, FEV)


# ---------------------------------------------------------------------------
# Rácios — churn, retenção e LTV
# ---------------------------------------------------------------------------

def test_churn_fev(df):
    # 2 perdidas / 3 ativas no início de Fev (= ativas de Jan) = 66,67%
    assert taxa_churn(df, FEV) == pytest.approx(66.67, abs=0.01)


def test_churn_sem_mes_anterior_devolve_zero(df):
    # JAN - 1 = Dez 2025, sem dados na fixture -> base 0 -> guarda devolve 0.0
    assert taxa_churn(df, JAN) == 0.0


def test_retencao_fev(df):
    assert taxa_retencao(df, FEV) == pytest.approx(33.33, abs=0.01)


def test_churn_e_retencao_somam_cem(df):
    # invariante da definição: retenção = 100 - churn
    assert taxa_churn(df, FEV) + taxa_retencao(df, FEV) == pytest.approx(100.0)


# ltv_estimado é uma função pura (só recebe números) -> não precisa da fixture

def test_ltv():
    # churn de 5%/mês -> vida média 1/0,05 = 20 meses -> 30€ x 20 = 600€
    assert ltv_estimado(30.0, 5.0) == pytest.approx(600.0)


def test_ltv_com_churn_zero_devolve_zero():
    # sem churn a vida média seria infinita; a função corta em 0.0
    assert ltv_estimado(30.0, 0.0) == 0.0