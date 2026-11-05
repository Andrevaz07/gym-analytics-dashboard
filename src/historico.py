"""
KPIs históricos mês a mês.

Devolve uma tabela com uma linha por mês e um KPI por coluna, para o
intervalo pedido. Pensado para gráficos de evolução e para relatórios.

NOTA: churn / retenção / LTV dependem do mês anterior. No primeiro mês
do intervalo o valor anterior já existe na BD se houver pagamentos
desse mês, logo são fiáveis. Para meses futuros (parciais) os números
ficam inflacionados pela data freshness.
"""
from __future__ import annotations
import pandas as pd

from src.kpis import (
    n_socias_ativas_no_mes,
    n_novos_socios_no_mes,
    n_socios_perdidos_no_mes,
    mrr_no_mes,
    arpu_no_mes,
    taxa_churn,
    taxa_retencao,
    ltv_estimado,
    faturacao_total_no_mes,
)
from src.renovacoes import _fim_fidelizacao, _fim_bloco_prepago


def ultimo_mes_fechado(ultimo_dia_com_dados: pd.Timestamp) -> pd.Period:
    """
    Último mês que se pode mostrar sem enganar quem lê a tabela.

    O mês do snapshot só entra se a exportação tiver chegado ao fim
    dele. As duas convenções de exportação exigem respostas opostas, e
    esta comparação dá a certa nas duas sem precisar de saber qual está
    em uso:

    - Até 2026-07 exportava-se a meio do mês. O ficheiro de 13-05
      deixava Maio pela metade; mostrá-lo dava um mês artificialmente
      fraco, com meia receita e churn inflacionado.
    - Desde a convenção de 2026-07-31 os ficheiros fecham meses
      inteiros. Aí descartar o último mês escondia dados bons — Julho
      completo desaparecia do painel.

    Limitação: a cobertura é o último `pag_data` que existe na BD, não
    a janela que se pediu à fonte. Um mês que feche sem nenhum
    pagamento no último dia é tratado como incompleto. Erra para o lado
    conservador — esconde um mês bom, nunca mostra um mês pela metade.

    Args:
        ultimo_dia_com_dados: o `pag_data` mais recente na BD.

    Returns:
        O Period mensal do último mês que se pode mostrar.
    """
    mes = ultimo_dia_com_dados.to_period("M")
    chegou_ao_fim = ultimo_dia_com_dados.normalize() == mes.end_time.normalize()
    return mes if chegou_ao_fim else mes - 1


def kpis_mensais(
    df: pd.DataFrame,
    mes_inicio: pd.Period,
    mes_fim: pd.Period,
) -> pd.DataFrame:
    """
    Calcula todos os KPIs principais para cada mês no intervalo (inclusivo).

    Args:
        df: DataFrame de pagamentos limpos (output de repository.pagamentos()).
        mes_inicio: primeiro mês, ex: pd.Period("2025-01", "M").
        mes_fim: último mês.

    Returns:
        DataFrame indexado por mês (string YYYY-MM) com colunas:
        ativas, novos, perdidos, mrr, faturacao, arpu, churn_pct,
        saidas_3m_pct, retencao_pct, ltv, renovacao_n. `renovacao_n` vem a None no último mês
        coberto pelo export — ver o comentário do horizonte no corpo.
    """
    fim_fid = _fim_fidelizacao(df)
    fim_bloco = _fim_bloco_prepago(df)

    # O último mês coberto pelo export é um horizonte artificial para o
    # fim de bloco pré-pago: quem paga ao mês tem sempre esse mês como
    # max(parcelas_disponivel), portanto TODA a sócia activa lá cai. Em
    # Julho de 2026 dava 345 contra 33 em Junho. Não mede nada, e por
    # isso `renovacao_n` fica a None nesse mês. Os outros KPIs do mês
    # não sofrem — só este depende de uma data de FIM, que é o que o
    # horizonte falsifica.
    mes_horizonte = df["pag_data"].max().to_period("M")

    # Saídas da média de 3 meses: soma das saídas dos três meses a dividir
    # pela soma das três bases, não a média de três percentagens — assim
    # um mês com menos sócias não pesa o mesmo que um cheio. Calculado com
    # dois meses de folga antes de mes_inicio, para o primeiro mês da
    # tabela (o homólogo do primeiro mês escolhível) não vir vazio.
    janela = pd.period_range(mes_inicio - 2, mes_fim, freq="M")
    saidas = {m: n_socios_perdidos_no_mes(df, m) for m in janela}
    bases = {m: n_socias_ativas_no_mes(df, m - 1) for m in janela}

    def _saidas_3m(m: pd.Period) -> float | None:
        base = sum(bases[m - k] for k in range(3))
        return round(sum(saidas[m - k] for k in range(3)) / base * 100, 2) if base else None

    periodos = pd.period_range(mes_inicio, mes_fim, freq="M")
    linhas = []
    for m in periodos:
        ativas = n_socias_ativas_no_mes(df, m)
        novos = n_novos_socios_no_mes(df, m)
        perdidos = n_socios_perdidos_no_mes(df, m)
        mrr = mrr_no_mes(df, m)
        faturacao = faturacao_total_no_mes(df, m)
        arpu = arpu_no_mes(df, m)
        churn = taxa_churn(df, m)
        retencao = taxa_retencao(df, m)
        ltv = ltv_estimado(arpu, churn) if churn > 0 else float("nan")

        # Tamanho da lista que teria sido gerada para este mês como mes_alvo.
        # Contamos pelas datas de fim em renovacoes.py (sem filtrar por "ativa
        # hoje", que enviesaria o histórico — uma sócia que renovou em 2025
        # pode hoje já não estar ativa, e nesse mês teria entrado na lista).
        ids_fid = set(fim_fid[fim_fid.dt.to_period("M") == m].index)
        ids_bloco = set(fim_bloco[fim_bloco.dt.to_period("M") == m].index)
        renovacao_n = None if m == mes_horizonte else len(ids_fid | ids_bloco)

        linhas.append(
            {
                "mes": str(m),
                "ativas": ativas,
                "novos": novos,
                "perdidos": perdidos,
                "mrr": round(mrr, 2),
                "faturacao": round(faturacao, 2),
                "arpu": round(arpu, 2),
                "churn_pct": round(churn, 2),
                "saidas_3m_pct": _saidas_3m(m),
                "retencao_pct": round(retencao, 2),
                "ltv": round(ltv, 2) if not pd.isna(ltv) else None,
                "renovacao_n": renovacao_n,
            }
        )
    return pd.DataFrame(linhas).set_index("mes")


def kpis_agregados(tabela_mensal: pd.DataFrame) -> dict:
    """
    Calcula agregados sobre uma tabela mensal de KPIs.

    Pensado para alimentar cartões de overview no relatório: o que mudou
    entre o início e o fim do período, médias dos KPIs voláteis (ARPU,
    churn), e totais (novos / perdidos).

    Args:
        tabela_mensal: output de kpis_mensais.

    Returns:
        dict pronto a usar em templates. Crescimentos em percentagem.
    """
    primeira = tabela_mensal.iloc[0]
    ultima = tabela_mensal.iloc[-1]
    arpu_medio = float(tabela_mensal["arpu"].mean())
    churn_medio = float(tabela_mensal["churn_pct"].mean())
    return {
        "periodo": f"{tabela_mensal.index[0]} → {tabela_mensal.index[-1]}",
        "n_meses": len(tabela_mensal),
        "ativas_inicio": int(primeira["ativas"]),
        "ativas_fim": int(ultima["ativas"]),
        "crescimento_socias_pct": ((ultima["ativas"] / primeira["ativas"]) - 1) * 100,
        "mrr_inicio": float(primeira["mrr"]),
        "mrr_fim": float(ultima["mrr"]),
        "crescimento_mrr_pct": ((ultima["mrr"] / primeira["mrr"]) - 1) * 100,
        "faturacao_inicio": float(primeira["faturacao"]),
        "faturacao_fim": float(ultima["faturacao"]),
        "crescimento_faturacao_pct": ((ultima["faturacao"] / primeira["faturacao"]) - 1) * 100,
        "faturacao_total_periodo": float(tabela_mensal["faturacao"].sum()),
        "arpu_medio": arpu_medio,
        "churn_medio": churn_medio,
        "retencao_media": 100.0 - churn_medio,
        # LTV calculado sobre médias (mais estável que LTV mensal isolado).
        "ltv_anualizado": (arpu_medio / (churn_medio / 100.0)) if churn_medio > 0 else float("nan"),
        "total_novos": int(tabela_mensal["novos"].sum()),
        "total_perdidos": int(tabela_mensal["perdidos"].sum()),
    }


def kpis_ano_ate(tabela_mensal: pd.DataFrame, mes: str) -> dict:
    """
    Acumulado do ano até ao mês dado — de Janeiro desse ano até `mes`.

    Escolher Dezembro dá o ano inteiro. Duas escolhas:

    - O crescimento de sócias conta desde Dezembro do ano anterior, não
      desde Janeiro: senão as entradas de Janeiro ficavam fora da conta,
      e escolher Janeiro dava sempre 0%.
    - As saídas são soma das saídas ÷ soma das bases (as ativas do mês
      anterior a cada mês), como no cartão de 3 meses — não a média das
      percentagens, que dava a um mês pequeno o peso de um cheio.

    Args:
        tabela_mensal: output de kpis_mensais. Tem de ter Dezembro do
            ano anterior para o crescimento e para a base de Janeiro; sem
            ele, usa o primeiro mês que houver.
        mes: o mês escolhido, "YYYY-MM".

    Returns:
        dict com inicio, fim, crescimento_socias_pct, faturacao_total,
        total_novos e saidas_pct.
    """
    fim = pd.Period(mes, "M")
    inicio = pd.Period(f"{fim.year}-01", "M")
    meses = [
        str(m) for m in pd.period_range(inicio, fim, freq="M")
        if str(m) in tabela_mensal.index
    ]
    ano = tabela_mensal.loc[meses]

    dezembro = str(inicio - 1)
    ativas_inicio = (
        tabela_mensal.loc[dezembro, "ativas"]
        if dezembro in tabela_mensal.index
        else ano["ativas"].iloc[0]
    )

    anteriores = [str(pd.Period(m, "M") - 1) for m in meses]
    com_base = [(m, a) for m, a in zip(meses, anteriores) if a in tabela_mensal.index]
    saidas = sum(tabela_mensal.loc[m, "perdidos"] for m, _ in com_base)
    bases = sum(tabela_mensal.loc[a, "ativas"] for _, a in com_base)

    return {
        "inicio": meses[0],
        "fim": meses[-1],
        "crescimento_socias_pct": (
            (ano["ativas"].iloc[-1] / ativas_inicio - 1) * 100 if ativas_inicio else 0.0
        ),
        "faturacao_total": float(ano["faturacao"].sum()),
        "total_novos": int(ano["novos"].sum()),
        "saidas_pct": saidas / bases * 100 if bases else 0.0,
    }


if __name__ == "__main__":
    from pathlib import Path
    from src.db import conectar
    from src.repository import pagamentos

    conn = conectar()
    df = pagamentos(conn)

    tabela = kpis_mensais(
        df,
        pd.Period("2025-01", "M"),
        pd.Period("2026-04", "M"),
    )

    pd.options.display.float_format = "{:,.2f}".format
    print(tabela.to_string())

    out = Path("data") / "historico_2025_2026-04.csv"
    tabela.to_csv(out)
    print(f"\nGuardado em: {out}")

    conn.close()
