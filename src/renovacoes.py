"""
Listas accionáveis de renovação para a gerente.

Duas listas, ambas construídas a partir do snapshot de pagamentos:

- Lista 1 — Fim de fidelização: sócias cuja fidelização obrigatória de
  3 meses (a contar da última inscrição) termina no mês-alvo.
- Lista 2 — Fim de bloco pré-pago: sócias de plano > 1 mês cujo
  adiantamento (max parcelas_disponivel) se esgota no mês-alvo. Os meses
  oferecidos contam (não filtramos por valor); as mensais ficam de fora
  porque renovam automaticamente.

O mês-alvo é, por omissão, o mês seguinte ao do snapshot (contacto com
1 mês de antecedência).

Ver memória project_listas_renovacao para a especificação validada.
"""

import pandas as pd

from src.kpis import PLANOS_PRINCIPAIS

# Regex que apanha todas as linhas de pagamento de inscrição/reinscrição.
# Detetamos pela DESCRIÇÃO (não pela família) porque "Inscrição - 1º
# Pagamento" tem inv_familia vazia.
_PADRAO_INSCRICAO = "inscri"

# Dentro das famílias de plano principal existem rubricas que NÃO são plano e
# inflavam a cobertura (Lista 2) ou poluíam a etiqueta plano/valor (output):
#   - "Taxa de Congelamento": sócia suspensa, não pré-paga.
#   - "Multa atraso mensalidade": penalização, não plano.
#   - "Kid Extra Ballet": extra avulso, não a mensalidade principal.
# Confirmado que nenhum plano legítimo contém estas palavras.
_PADRAO_NAO_PLANO = r"Congelamento|Multa|Extra"

# Meses de fidelização obrigatória a contar da inscrição (inclui o mês de
# inscrição: inscrita em Março → livre a entrar em Junho = Março + 3).
_MESES_FIDELIZACAO = 3


def _mes_corrente(df: pd.DataFrame) -> pd.Period:
    """Mês do snapshot, inferido da data de pagamento mais recente."""
    return df["pag_data"].max().to_period("M")


def _fim_fidelizacao(df: pd.DataFrame) -> pd.Series:
    """Data de fim de fidelização por sócia (última inscrição + 3 meses)."""
    mask = df["inv_descricao"].str.contains(
        _PADRAO_INSCRICAO, case=False, na=False
    )
    ultima_insc = df.loc[mask].groupby("utente_no_insc")["pag_data"].max()
    return ultima_insc + pd.DateOffset(months=_MESES_FIDELIZACAO)


def _mascara_plano_real(df: pd.DataFrame) -> pd.Series:
    """Pagamentos válidos de plano principal, sem rubricas não-plano.

    Filtra: pag_anulado=='Não', família em PLANOS_PRINCIPAIS, e descarta
    descrições com Congelamento/Multa/Extra.
    """
    return (
        (df["pag_anulado"] == "Não")
        & (df["inv_familia"].isin(PLANOS_PRINCIPAIS))
        & (~df["parcelas_descricao"].str.contains(
            _PADRAO_NAO_PLANO, case=False, na=False, regex=True))
    )


def _fim_bloco_prepago(df: pd.DataFrame) -> pd.Series:
    """Último mês coberto por sócia, só sobre planos principais reais.

    Exclui add-ons (Avaliações/Nutrição) e rubricas não-plano. Meses
    oferecidos (valor 0) contam — não filtramos por valor.
    """
    return (
        df[_mascara_plano_real(df)]
        .groupby("utente_no_insc")["parcelas_disponivel"]
        .max()
    )


def _atributos_socias(df: pd.DataFrame) -> pd.DataFrame:
    """Identidade + plano + valor por sócia, para vestir as listas.

    - nome/gestor/tipo: linha mais recente por pag_data.
    - plano: descrição da última parcela de plano real (sem "(Mês/Ano)").
    - valor: último valor > 0 (evita apanhar um mês oferecido a 0€).

    Usar a ÚLTIMA parcela (e não a moda) é o que captura o plano atual:
    sócias reinscritas em plano novo, mudanças de preço, sócias recentes
    com poucos dados — todas dão o sinal certo. O ruído (multas, extras,
    congelamentos) já foi removido a montante via _mascara_plano_real.
    """
    ident = (
        df.sort_values("pag_data")
        .groupby("utente_no_insc")[
            ["doc_nome", "utente_gestor", "utente_tipo_socio"]
        ]
        .last()
    )

    pr = df[_mascara_plano_real(df)].sort_values("parcelas_disponivel")

    plano = (
        pr.groupby("utente_no_insc")["parcelas_descricao"]
        .last()
        .str.replace(r"^\(.*?\)\s*", "", regex=True)
    )
    valor = (
        pr[pr["parcelas_valor_liquido"] > 0]
        .groupby("utente_no_insc")["parcelas_valor_liquido"]
        .last()
        .round(2)
    )

    return ident.assign(plano=plano, valor=valor)


def listas_renovacao(
    df: pd.DataFrame,
    mes_alvo: pd.Period | None = None,
    *,
    ativas: set[int],
) -> pd.DataFrame:
    """Lista contactável de sócias a renovar no mês-alvo.

    Junta a Lista 1 (fim de fidelização) e a Lista 2 (fim de bloco
    pré-pago), filtradas a sócias ativas. Sócias em ambas aparecem numa
    só linha, com os dois motivos.

    Args:
        df: DataFrame de pagamentos limpos (output de clean_pagamentos).
        mes_alvo: mês a contactar. Por omissão, mês do snapshot + 1.
        ativas: quem é sócia agora (src.socias.ids_socias). Obrigatório e
            sem valor por omissão de propósito: calcular isto a partir do
            df sozinho dá a resposta errada — o estado da sócia vive
            espalhado por todas as linhas dela, com safras diferentes.

    Returns:
        DataFrame com colunas: id, nome, gestor, tipo, plano, valor,
        data_fim, motivo. Ordenado por data_fim e nome.
    """
    if mes_alvo is None:
        mes_alvo = _mes_corrente(df) + 1


    def _filtrar(serie: pd.Series) -> pd.Series:
        serie = serie[serie.index.isin(ativas)]
        return serie[serie.dt.to_period("M") == mes_alvo]

    fidelizacao = _filtrar(_fim_fidelizacao(df))
    bloco = _filtrar(_fim_bloco_prepago(df))

    l1 = pd.DataFrame({"data_fim": fidelizacao, "motivo": "Fim de fidelização"})
    l2 = pd.DataFrame({"data_fim": bloco, "motivo": "Fim de bloco pré-pago"})

    agg = (
        pd.concat([l1, l2])
        .groupby(level=0)
        .agg(
            data_fim=("data_fim", "min"),
            motivo=("motivo", lambda s: " + ".join(sorted(set(s)))),
        )
    )

    final = (
        agg.join(_atributos_socias(df))
        .reset_index()
        .rename(
            columns={
                "utente_no_insc": "id",
                "doc_nome": "nome",
                "utente_gestor": "gestor",
                "utente_tipo_socio": "tipo",
            }
        )
    )

    # tipo vem de uma coluna categórica — converter para texto antes de
    # preencher, senão "—" não é uma categoria válida.
    final["tipo"] = final["tipo"].astype("object").fillna("—")
    final = final[
        ["id", "nome", "gestor", "tipo", "plano", "valor", "data_fim", "motivo"]
    ]
    return final.sort_values(["data_fim", "nome"]).reset_index(drop=True)
