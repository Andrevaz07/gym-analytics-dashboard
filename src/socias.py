"""
Quem é sócia AGORA.

Este módulo responde a uma pergunta só: quem é sócia do ginásio neste
momento. É diferente de `kpis.socias_ativas_no_mes()`, que responde a
"quem foi sócia durante o mês X" — essa baseia-se em pagamentos e
funciona para qualquer mês desde 2011.

As duas discordam de propósito. Quem pagou Julho e cancelou em Agosto
conta numa e não na outra, e ambas estão certas: os pagamentos param no
fim da janela exportada, o estado foi lido no dia da extração.

Duas armadilhas que este módulo existe para evitar:

1. O `utente_status` vem repetido em todas as linhas da sócia, e desde
   que a janela de exportação passou a ser de 6 meses as linhas antigas
   deixaram de ser reescritas. A mesma sócia tem linhas a dizer "A" e
   linhas a dizer "M". Perguntar "tem alguma linha A?" responde na
   verdade "já alguma vez foi activa" — só pode crescer, e dava 448
   sócias quando o valor certo eram 380.

2. Uma sócia que não vem na extração mais recente não tem estado
   conhecido, tem o último estado que se lhe conheceu. Doze sócias
   marcadas "A" não pagam nada desde Junho de 2022: continuam "A" no
   sistema do ginásio e nunca mais foram mencionadas.
"""

from __future__ import annotations

import sqlite3

import pandas as pd

# Estados em que a sócia AINDA é sócia. A suspensa (S) pausou a
# mensalidade por um período prolongado — férias, saúde, motivos
# pessoais — mas mantém o vínculo, precisamente para não ter de pagar
# inscrição outra vez ao voltar (custa €28 a €61, e 83 sócias já a
# pagaram duas vezes). Não é uma saída: 55% das suspensões acontecem
# entre Julho e Setembro, e de quem já congelou, metade está activa hoje.
#
# Fora ficam M (ex-sócia), D (dívida em litígio) e P (indefinido — nem a
# equipa do ginásio sabe o que significa na tabela).
ESTADOS_SOCIA = frozenset({"A", "S"})

# Estados de quem se espera que APAREÇA no ginásio. É o único sítio onde
# A e S se separam: a suspensa está ausente por combinação, portanto
# sinalizá-la como "não vem há 60 dias" é um alarme falso e faz telefonar
# a quem já avisou que ia estar fora.
ESTADOS_COM_PRESENCA_ESPERADA = frozenset({"A"})


def _cobertura_mais_recente(conn: sqlite3.Connection) -> tuple[str, str] | None:
    """Janela (de, até) do snapshot de pagamentos mais recente."""
    linha = conn.execute(
        """SELECT cobertura_de, cobertura_ate FROM _raw_snapshots
           WHERE tabela = 'pagamentos'
           ORDER BY snapshot_data DESC LIMIT 1"""
    ).fetchone()
    return (linha[0], linha[1]) if linha and linha[0] and linha[1] else None


def socias_atuais(conn: sqlite3.Connection) -> pd.DataFrame:
    """
    Uma linha por sócia, com o estado mais recente e a sua frescura.

    Colunas:
        utente_no_insc          índice
        estado                  A/M/S/P/D da extração mais recente que a mencionou
        veio_na_ultima_extracao True se a extração mais recente falou dela

    O estado vem da linha com `atualizado_em_snapshot` mais alto. Esse
    carimbo regista quando a linha MUDOU, não quando foi vista — mas
    serve na mesma, porque os campos da sócia são reescritos em conjunto:
    se o estado mudou, as linhas novas têm carimbo novo E estado novo; se
    não mudou, todas as linhas concordam e qualquer uma serve.

    (Ordenar por `parcelas_disponivel` em vez do carimbo parece
    equivalente e quase sempre é, mas erra quando a sócia tem linhas de
    mês futuro lançadas por uma extração anterior — foi o caso de uma
    sócia com avaliações pré-agendadas a €0 que a dava como activa
    depois de ter cancelado.)

    `veio_na_ultima_extracao` compara `pag_data` com a cobertura do
    último snapshot em `_raw_snapshots`. Reproduz exactamente o conjunto
    de sócias do ficheiro (549 = 549, verificado). Quando não há
    cobertura registada, vem tudo a True — sem informação, não se inventa
    uma exclusão.
    """
    df = pd.read_sql_query(
        """SELECT utente_no_insc, utente_status, atualizado_em_snapshot, pag_data
           FROM _raw_pagamentos WHERE utente_no_insc IS NOT NULL""",
        conn,
        parse_dates=["pag_data"],
    )
    if df.empty:
        return pd.DataFrame(
            {"estado": [], "veio_na_ultima_extracao": []},
            index=pd.Index([], name="utente_no_insc"),
        )

    estado = (
        df.sort_values("atualizado_em_snapshot")
        .groupby("utente_no_insc")["utente_status"]
        .last()
        .rename("estado")
    )

    janela = _cobertura_mais_recente(conn)
    if janela is None:
        vistas = set(estado.index)
    else:
        # Datas, não strings: pag_data vem como "2026-07-31 00:00:00" e a
        # cobertura como "2026-07-31" — comparadas como texto, o último
        # dia da janela ficava de fora.
        de = pd.Timestamp(janela[0])
        ate = pd.Timestamp(janela[1]) + pd.Timedelta(days=1)
        vistas = set(
            df.loc[(df["pag_data"] >= de) & (df["pag_data"] < ate), "utente_no_insc"]
        )

    return pd.DataFrame(
        {
            "estado": estado,
            "veio_na_ultima_extracao": estado.index.isin(list(vistas)),
        }
    )


def ids_socias(socias: pd.DataFrame) -> set[int]:
    """
    IDs de quem é sócia agora: estado A ou S, e mencionada na última
    extração. As duas condições são precisas — sem a segunda entram
    sócias cujo "A" ficou congelado numa extração antiga.
    """
    m = socias["estado"].isin(ESTADOS_SOCIA) & socias["veio_na_ultima_extracao"]
    return {int(i) for i in socias.index[m]}


def ids_com_presenca_esperada(socias: pd.DataFrame) -> set[int]:
    """IDs de quem se espera no ginásio — base da lista de risco."""
    m = (
        socias["estado"].isin(ESTADOS_COM_PRESENCA_ESPERADA)
        & socias["veio_na_ultima_extracao"]
    )
    return {int(i) for i in socias.index[m]}
