"""
Receita por área de serviço, e por plano dentro de cada área.

Responde a "quanto da faturação vem de cada coisa" num período à escolha.
As contas são as do cartão Faturação (`kpis.faturacao_total_no_mes`): sem
IVA, sem parcelas anuladas, cada parcela no seu mês de serviço. O total de
um período é por isso a soma desse cartão nos meses escolhidos.

Dois passos, para o painel não refazer o trabalho pesado a cada clique:
`receita_mensal` agrega as ~100 mil linhas uma vez (fica em cache), e
`por_area` / `detalhe` só somam meses dessa tabela pequena.
"""
from __future__ import annotations

import re

import pandas as pd

# Área de cada inv_familia, comparada em minúsculas — o software de gestão escreve
# "kids" e "cacifos" em minúsculas e as outras famílias com maiúscula.
AREAS = {
    "mensalidades": "Mensalidades",
    "personal trainer": "Personal Trainer",
    "nutrição": "Nutrição",
    "avaliações": "Avaliações",
    "kids": "Kids",
    "inscrição": "Inscrições",
    # Produtos vendidos na receção, uma família por marca.
    "loja": "Loja e bar",
    "prozis": "Loja e bar",
    "captain kombucha": "Loja e bar",
    "naturitas": "Loja e bar",
    "iswari": "Loja e bar",
    "miolo": "Loja e bar",
    "alimentação diversos": "Loja e bar",
    "alpro": "Loja e bar",
    "merchandising": "Loja e bar",
    "solgar": "Loja e bar",
}

# Cacifos, cursos, aula experimental — e qualquer família nova. Uma família
# desconhecida vai para aqui e não para a loja: pôr um serviço novo no meio
# dos produtos enganava; em "Outros" fica à vista no detalhe, pelo nome.
OUTROS = "Outros"

# Nestas áreas o detalhe é por família (a marca, na loja), não por produto:
# "Prozis" diz mais do que quarenta sabores de barra proteica.
AREAS_POR_FAMILIA = {"Loja e bar", OUTROS}

# O mesmo plano aparece com e sem "25" no fim ("... 25", "...Online25"): a
# tabela de preços de 2025 ao lado da antiga, que algumas sócias mantêm.
# Juntam-se — decisão de 27-10-2026. Só o "25": "Personal Shopper 2" é
# outro produto, com outro preço.
_TARIFA = re.compile(r"\s*25$")

# "Plano Pack familia" e "Pack familia" são o mesmo plano com dois nomes.
_PREFIXO_PLANO = re.compile(r"^plano\s+")

_TAXAS = re.compile(r"^(taxa|multa|acerto)\b", re.IGNORECASE)
TAXAS = "Taxas, multas e acertos"
SEM_NOME = "(sem nome)"


def _sem_tarifa(descricao) -> str:
    if pd.isna(descricao) or not str(descricao).strip():
        return SEM_NOME
    texto = str(descricao).strip()
    if _TAXAS.match(texto):
        return TAXAS
    return _TARIFA.sub("", texto)


def _nome_mais_comum(chave: pd.Series, nome: pd.Series) -> pd.Series:
    """
    Um nome só para cada chave: o que aparece em mais linhas.

    Calculado sobre o histórico todo, para o mesmo plano não mudar de nome
    conforme o período escolhido.
    """
    nome_da_chave = (
        pd.DataFrame({"chave": chave, "nome": nome})
        .value_counts()
        .reset_index()
        .drop_duplicates("chave")      # value_counts ordena do mais frequente
        .set_index("chave")["nome"]
    )
    return chave.map(nome_da_chave)


def _nomes_de_plano(descricoes: pd.Series) -> pd.Series:
    """
    Nome do plano de cada linha, com as versões de tarifa juntas.

    Planos que só diferem em maiúsculas ou no "Plano " à frente ficam com um
    nome só.
    """
    base = descricoes.map(_sem_tarifa)
    chave = base.str.lower().str.replace(_PREFIXO_PLANO, "", regex=True)
    return _nome_mais_comum(chave, base)


def receita_mensal(df: pd.DataFrame) -> pd.DataFrame:
    """
    Receita de cada mês de serviço, por área e por plano.

    Args:
        df: DataFrame de pagamentos (repository.pagamentos).

    Returns:
        DataFrame com `mes` (Period mensal), `area`, `item` e `euros`.
    """
    ok = df[df["pag_anulado"] == "Não"]
    familia = ok["inv_familia"].fillna("").astype(str).str.strip()
    area = familia.str.lower().map(AREAS).fillna(OUTROS)

    item = _nomes_de_plano(ok["inv_descricao"])
    nome_familia = _nome_mais_comum(familia.str.lower(), familia.replace("", SEM_NOME))
    item = item.where(~area.isin(AREAS_POR_FAMILIA), nome_familia)

    tabela = pd.DataFrame({
        "mes": ok["parcelas_disponivel"].dt.to_period("M"),
        "area": area,
        "item": item,
        "euros": ok["parcelas_valor_liquido"],
    })
    # Sem mês de serviço não há onde a pôr — o cartão Faturação também a
    # deixa de fora.
    return tabela.groupby(["mes", "area", "item"], as_index=False)["euros"].sum()


def _no_periodo(mensal: pd.DataFrame, inicio, fim) -> pd.DataFrame:
    inicio, fim = pd.Period(inicio, "M"), pd.Period(fim, "M")
    return mensal[(mensal["mes"] >= inicio) & (mensal["mes"] <= fim)]


def por_area(mensal: pd.DataFrame, inicio, fim) -> pd.DataFrame:
    """
    Receita de cada área entre dois meses, inclusive.

    Returns:
        DataFrame com `area`, `euros` e `pct` (do total do período), da área
        com mais receita para a com menos, e "Outros" sempre no fim.
    """
    tabela = (
        _no_periodo(mensal, inicio, fim)
        .groupby("area", as_index=False)["euros"].sum()
    )
    tabela = tabela[tabela["euros"] != 0]
    tabela["pct"] = 100 * tabela["euros"] / tabela["euros"].sum()
    tabela["_fim"] = tabela["area"] == OUTROS
    return (
        tabela.sort_values(["_fim", "euros"], ascending=[True, False])
        .drop(columns="_fim")
        .reset_index(drop=True)
    )


def detalhe(mensal: pd.DataFrame, area: str, inicio, fim) -> pd.DataFrame:
    """
    Receita de cada plano (ou marca) de uma área entre dois meses.

    Returns:
        DataFrame com `item`, `euros`, `pct_area` e `pct_total`, do que tem
        mais receita para o que tem menos.
    """
    periodo = _no_periodo(mensal, inicio, fim)
    total = periodo["euros"].sum()
    tabela = (
        periodo[periodo["area"] == area]
        .groupby("item", as_index=False)["euros"].sum()
    )
    tabela = tabela[tabela["euros"] != 0]
    tabela["pct_area"] = 100 * tabela["euros"] / tabela["euros"].sum()
    tabela["pct_total"] = 100 * tabela["euros"] / total
    return tabela.sort_values("euros", ascending=False).reset_index(drop=True)
