"""
Testes de src.historico.

Por agora só `ultimo_mes_fechado`, que decide onde a tabela mensal
acaba. É pouco código mas decide o que a gerente vê como "último mês",
e as duas convenções de exportação exigem respostas opostas.
"""

import pandas as pd
import pytest

from src.historico import ultimo_mes_fechado


def test_exportacao_a_meio_do_mes_descarta_esse_mes():
    """
    Convenção antiga: o ficheiro de 13-05-2026 deixava Maio pela
    metade. Mostrá-lo dava meia receita e churn inflacionado.
    """
    assert ultimo_mes_fechado(pd.Timestamp("2026-05-13")) == pd.Period("2026-04", "M")


def test_exportacao_que_fecha_o_mes_mostra_esse_mes():
    """
    Convenção nova (2026-07-31): o ficheiro cobre Julho inteiro, logo
    Julho entra. Era este o mês que o painel escondia.
    """
    assert ultimo_mes_fechado(pd.Timestamp("2026-07-31")) == pd.Period("2026-07", "M")


def test_penultimo_dia_do_mes_ainda_conta_como_incompleto():
    """A cobertura tem de chegar ao fim, não perto do fim."""
    assert ultimo_mes_fechado(pd.Timestamp("2026-07-30")) == pd.Period("2026-06", "M")


def test_hora_no_timestamp_nao_estraga_a_comparacao():
    """
    `pag_data` é datetime, não date. Um carimbo com horas no último dia
    do mês continua a fechar o mês — comparar Timestamps em bruto
    falhava aqui, porque end_time é 23:59:59.999999999.
    """
    assert ultimo_mes_fechado(pd.Timestamp("2026-07-31 14:30:00")) == pd.Period(
        "2026-07", "M"
    )


def test_fim_de_fevereiro_em_ano_bissexto():
    """29 de Fevereiro fecha Fevereiro; 28 não, num ano bissexto."""
    assert ultimo_mes_fechado(pd.Timestamp("2024-02-29")) == pd.Period("2024-02", "M")
    assert ultimo_mes_fechado(pd.Timestamp("2024-02-28")) == pd.Period("2024-01", "M")


def test_fim_de_ano_recua_para_dezembro_do_ano_anterior():
    """Janeiro incompleto tem de recuar um ano, não só um mês."""
    assert ultimo_mes_fechado(pd.Timestamp("2026-01-15")) == pd.Period("2025-12", "M")


def test_renovacao_n_fica_vazia_no_mes_do_horizonte(df_base):
    """
    O último mês coberto pelo export é um horizonte artificial: quem
    paga ao mês tem sempre esse mês como max(parcelas_disponivel), por
    isso toda a gente activa lá cai. Contá-los daria uma "renovação em
    massa" que não existe — em Julho de 2026 dava 345 contra 33 em
    Junho. Vale mais não mostrar nada do que mostrar um número errado.
    """
    from src.historico import kpis_mensais

    horizonte = df_base["pag_data"].max().to_period("M")
    tabela = kpis_mensais(df_base, horizonte - 2, horizonte)

    # None passa a NaN ao construir o DataFrame — a coluna é numérica.
    assert pd.isna(tabela.loc[str(horizonte), "renovacao_n"])
    # Os meses anteriores continuam a contar normalmente.
    assert not pd.isna(tabela.loc[str(horizonte - 1), "renovacao_n"])


def test_horizonte_nao_afeta_os_outros_kpis_do_mes(df_base):
    """
    Só `renovacao_n` depende de uma data de FIM. Ativas e MRR do mês do
    horizonte são reais e têm de continuar a aparecer — foi por eles
    que se passou a mostrar o último mês.
    """
    from src.historico import kpis_mensais

    horizonte = df_base["pag_data"].max().to_period("M")
    linha = kpis_mensais(df_base, horizonte, horizonte).loc[str(horizonte)]

    assert linha["ativas"] is not None
    assert not pd.isna(linha["mrr"])


def _mensalidades(ids_por_mes: dict[str, range]) -> pd.DataFrame:
    """Uma mensalidade por sócia e por mês — só o que kpis_mensais lê."""
    linhas = []
    for mes, ids in ids_por_mes.items():
        for i in ids:
            linhas.append({
                "utente_no_insc": i,
                "parcelas_disponivel": pd.Timestamp(f"{mes}-01"),
                "pag_data": pd.Timestamp(f"{mes}-01"),
                "pag_anulado": "Não",
                "inv_familia": "Mensalidades",
                "inv_descricao": "Plano Mensal",
                "parcelas_descricao": "Mensalidade",
                "parcelas_valor_liquido": 30.0,
            })
    return pd.DataFrame(linhas)


def test_saidas_3_meses_soma_saidas_e_bases_em_vez_de_fazer_media():
    """
    10 sócias em Janeiro, 9 em Fevereiro, 5 em Março e Abril: saem 1, 4
    e 0. A média das três percentagens (10%, 44%, 0%) daria 18,1%; a
    conta certa — 5 saídas sobre 24 sócias de base — dá 20,8%. Um mês
    pequeno não pode pesar o mesmo que um mês cheio.

    Pedido só Abril, para provar também que os dois meses de folga são
    calculados lá dentro: sem eles, o primeiro mês da tabela vinha vazio.
    """
    from src.historico import kpis_mensais

    df = _mensalidades({
        "2026-01": range(1, 11),
        "2026-02": range(1, 10),
        "2026-03": range(1, 6),
        "2026-04": range(1, 6),
    })
    linha = kpis_mensais(df, pd.Period("2026-04", "M"), pd.Period("2026-04", "M")).loc["2026-04"]

    assert linha["saidas_3m_pct"] == round(5 / 24 * 100, 2)
    assert linha["churn_pct"] == 0.0  # o mês sozinho não teve saídas


def test_acumulado_do_ano_vai_de_janeiro_ao_mes_escolhido():
    """
    Dezembro 10 sócias; Janeiro saem 2 e entra 1 (9); Fevereiro entram 2
    (11); Março saem 2 (9). Escolhido Fevereiro: o crescimento conta desde
    Dezembro (11 contra 10), as novas somam Janeiro e Fevereiro (3), e as
    saídas são 2 sobre as bases de Janeiro e Fevereiro (10 + 9). Março
    fica de fora — é depois do mês escolhido.
    """
    from src.historico import kpis_ano_ate, kpis_mensais

    df = _mensalidades({
        "2025-12": range(1, 11),
        "2026-01": [*range(1, 9), 11],
        "2026-02": [*range(1, 9), 11, 12, 13],
        "2026-03": [*range(1, 7), 11, 12, 13],
    })
    tabela = kpis_mensais(df, pd.Period("2025-12", "M"), pd.Period("2026-03", "M"))

    fev = kpis_ano_ate(tabela, "2026-02")
    assert (fev["inicio"], fev["fim"]) == ("2026-01", "2026-02")
    assert fev["crescimento_socias_pct"] == pytest.approx(10.0)
    assert fev["total_novos"] == 3
    assert fev["saidas_pct"] == pytest.approx(2 / 19 * 100)
    assert fev["faturacao_total"] == pytest.approx((9 + 11) * 30.0)

    # Janeiro sozinho já não dá 0%: conta contra Dezembro.
    assert kpis_ano_ate(tabela, "2026-01")["crescimento_socias_pct"] == pytest.approx(-10.0)
