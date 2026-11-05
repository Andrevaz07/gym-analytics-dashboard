"""
Dashboard interativo do ginásio (Streamlit).

Para correr:
    streamlit run src/dashboard.py

Lê directamente a base de dados local (`data/ginasio.sqlite`), que acumula
os snapshots do software de gestão. Ao contrário do relatório HTML estático,
aqui os números respondem ao clique — a gerente escolhe o mês e a lista
que quer ver, sem pedir nada a ninguém.

Actualizar é arrastar a exportação para `data/entrada/`: o painel
reconhece o relatório e ingere-o sozinho (ver `src/entrada.py`).

Cinco separadores:
  1. Visão Geral   — indicadores do mês escolhido + evolução dos últimos meses.
  2. Receita       — faturação por área e por plano, num período à escolha.
  3. Retenção      — sócias sem vir ao ginásio, cruzando presenças com pagamentos.
  4. Renovações    — fidelizações e blocos pré-pagos a terminar no mês seguinte.
  5. Dados         — tabela mês a mês e limitações conhecidas.

O visual vem de `src/visual.py`, partilhado com o relatório HTML.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# O `streamlit run src/dashboard.py` coloca a pasta do script (src/) no
# sys.path, não a raiz do projeto — sem isto, `from src.db import ...`
# rebenta com ModuleNotFoundError. Tem de vir antes dos imports de src.
_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

import pandas as pd
import streamlit as st

from src.db import DB_PATH, conectar, demo_proibida, e_demo
from src.entrada import (
    ficheiros_pousados, houve_novidades, pasta_nuvem, processar_entrada,
    ultima_copia_na_nuvem,
)
from src.repository import pagamentos
from src.historico import kpis_mensais, kpis_ano_ate, ultimo_mes_fechado
from src.receita import detalhe, por_area, receita_mensal
from src.renovacoes import listas_renovacao
from src.presencas_kpis import socias_em_risco
from src.socias import socias_atuais, ids_socias
from src.visual import (
    COR_ROSE, COR_ROSE_FORTE, COR_RED, COR_BLUE,
    formatar_euros, formatar_pct,
    grafico_distribuicao, grafico_linha, grafico_novos_perdidos,
)

# Os cartões comparam sempre com o mês homólogo, por isso a tabela tem de
# começar um ano antes do primeiro mês que se pode escolher.
MES_INICIO = pd.Period("2023-01", "M")

# Primeiro mês oferecido no seletor: garante que há sempre homólogo.
MES_INICIO_VISIVEL = pd.Period("2024-01", "M")

# A partir de quantos dias o snapshot deixa de ser "recente" e passa a
# merecer aviso no topo do dashboard.
DIAS_ATE_AVISO = 45


# --------------------------------------------------------------------- dados


@st.cache_data(show_spinner="A carregar os dados do ginásio...")
def carregar_tudo() -> dict:
    """
    Lê a base de dados e calcula tudo o que o dashboard mostra.

    Corre uma vez e fica em cache: o Streamlit reexecuta o script inteiro
    a cada clique, e sem cache os KPIs mensais seriam recalculados sobre
    ~95 mil linhas de cada vez.

    Devolve um dicionário em vez de vários valores soltos para o cache
    guardar um objecto só e a chamada no topo da página ficar legível.
    """
    conn = conectar()

    df = pagamentos(conn)
    risco = socias_em_risco(conn)
    snapshots = pd.read_sql_query(
        """SELECT snapshot_data, tabela, n_linhas, cobertura_de, cobertura_ate
           FROM _raw_snapshots ORDER BY snapshot_data""",
        conn,
    )

    # A lista de risco vem só com números de sócia — sem nome não é
    # accionável para quem vai pegar no telefone.
    nomes = (
        df.sort_values("pag_data")
        .groupby("utente_no_insc")["doc_nome"]
        .last()
    )
    risco = risco.copy()
    risco["nome"] = risco["utente_no_insc"].map(nomes)

    # O mês do snapshot só entra se a exportação chegou ao fim dele
    # (ver ultimo_mes_fechado). Antes assumia-se sempre incompleto, o
    # que era certo quando se exportava a meio do mês e passou a
    # esconder um mês bom quando a exportação passou a fechar meses.
    ultimo_dia_com_dados = df["pag_data"].max()
    mes_snapshot = ultimo_dia_com_dados.to_period("M")
    mes_fim = ultimo_mes_fechado(ultimo_dia_com_dados)

    tabela = kpis_mensais(df, MES_INICIO, mes_fim)
    receita = receita_mensal(df)
    socias = socias_atuais(conn)
    renovacoes = listas_renovacao(df, ativas=ids_socias(socias))

    # Para a gerente poder comparar com o que o software de gestão mostra: os
    # estados de quem veio na última exportação, e quantas continuam
    # marcadas "A" sem ter vindo — essas o software de gestão conta e o painel não.
    vistas = socias[socias["veio_na_ultima_extracao"]]
    estados = vistas["estado"].value_counts().to_dict()
    a_sem_pagamentos = int(
        ((socias["estado"] == "A") & ~socias["veio_na_ultima_extracao"]).sum()
    )

    conn.close()

    return {
        "tabela": tabela,
        "receita": receita,
        "renovacoes": renovacoes,
        "estados": estados,
        "a_sem_pagamentos": a_sem_pagamentos,
        "risco": risco,
        "snapshots": snapshots,
        "mes_snapshot": mes_snapshot,
        "data_snapshot": df["pag_data"].max().date(),
        "mes_fim": mes_fim,
    }


# --------------------------------------------------------------------- helpers de apresentação

NOMES_MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
               "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def rotulo_mes(periodo: str | pd.Period) -> str:
    """'2026-04' -> 'Abril de 2026'."""
    ano, mes = str(periodo).split("-")
    return f"{NOMES_MESES[int(mes) - 1]} de {ano}"


def rotulo_periodo(inicio: str, fim: str) -> str:
    """'2026-01', '2026-07' -> 'Janeiro a Julho de 2026'."""
    if inicio == fim:
        return rotulo_mes(fim)
    if inicio[:4] == fim[:4]:
        return f"{NOMES_MESES[int(inicio[5:]) - 1]} a {rotulo_mes(fim)}"
    return f"{rotulo_mes(inicio)} a {rotulo_mes(fim)}"


def _sem_zero_negativo(valor: float) -> float:
    """Arredondar pode produzir -0.0, que aparece como '-0' no cartão."""
    return 0.0 if valor == 0 else valor


def delta_numero(atual: float, anterior: float | None, sufixo: str = "") -> str | None:
    """Texto do delta para o st.metric. None quando não há mês anterior."""
    if anterior is None:
        return None
    diferenca = _sem_zero_negativo(round(atual - anterior))
    return f"{diferenca:+,.0f}{sufixo}".replace(",", " ")


def delta_pontos(atual: float, anterior: float | None) -> str | None:
    """Delta em pontos percentuais — para cancelamentos e retenção."""
    if anterior is None:
        return None
    diferenca = _sem_zero_negativo(round(atual - anterior, 1))
    return f"{diferenca:+.1f} pp"


def mes_homologo(mes: str) -> str:
    """'2026-04' -> '2025-04'. O mesmo mês do ano anterior."""
    ano, m = str(mes).split("-")
    return f"{int(ano) - 1}-{m}"


def valores_do_mes(tabela: pd.DataFrame, mes: str) -> tuple[pd.Series, pd.Series | None]:
    """
    Linha do mês escolhido e a do mês homólogo.

    A comparação é sempre com o mesmo mês do ano anterior, nunca com o mês
    imediatamente anterior: num ginásio a época do ano pesa demasiado
    (Janeiro enche com as resoluções de ano novo, Agosto esvazia com as
    férias), e uma comparação mensal mediria sobretudo o calendário.
    """
    homologo = mes_homologo(mes)
    anterior = tabela.loc[homologo] if homologo in tabela.index else None
    return tabela.loc[mes], anterior


# --------------------------------------------------------------------- página

st.set_page_config(
    page_title="o ginásio — Dashboard",
    page_icon="💗",
    layout="wide",
)

st.markdown(
    """
    <style>
      .stApp { background-color: #faf9f7; }
      [data-testid="stMetricValue"] { font-size: 30px; font-weight: 700; }
      [data-testid="stMetricLabel"] {
        text-transform: uppercase; letter-spacing: 1px; font-size: 11px;
      }
      [data-testid="stSidebar"] { background-color: #ffffff; }
    </style>
    """,
    unsafe_allow_html=True,
)

# No Mac da gerente a base fictícia nunca é a certa (ver demo_proibida).
# A faixa vermelha abaixo não chega lá: quem abre o painel todos os dias
# deixa de a ler, fica a olhar para sócias inventadas, e as extrações
# ficam paradas na pasta sem ninguém dar por isso. Pára antes de abrir a
# base — conectar() criava o ficheiro se ele não existisse.
if demo_proibida():
    st.error(
        "**O painel não abriu.** Está configurado para usar uma base de dados "
        "de demonstração, com sócias inventadas, e neste computador só pode "
        "mostrar os dados do ginásio.\n\n"
        "Os dados do ginásio não foram alterados, e as extrações que estejam "
        "na pasta **data/entrada** ficam lá à espera. Contacte quem mantém o "
        "painel.",
        icon="⛔",
    )
    st.caption(
        f"Pormenor técnico: a linha `GINASIO_DB` do ficheiro `.env` aponta para "
        f"`{DB_PATH.name}`. Apagar essa linha e voltar a abrir o painel."
    )
    st.stop()

if e_demo():
    st.error(
        "**Dados fictícios.** Este painel está a mostrar uma base de dados de "
        "demonstração, com sócias e valores inventados. Nenhum número desta "
        "página corresponde ao ginásio real.",
        icon="🧪",
    )


# ------------------------------------------------------- extrações novas

# Não há botão de upload: a extração entra por pasta. Quem quiser
# atualizar arrasta o ficheiro para data/entrada/ e o painel trata do
# resto — aqui, à interação seguinte, ou no lançador, ao arrancar.
#
# Em demonstração isto não corre: a base é fictícia e não pode receber
# um ficheiro real que alguém deixe cair na pasta por engano.
if not e_demo() and ficheiros_pousados():
    with st.spinner("A ler a extração nova — pode demorar um minuto."):
        resultados = processar_entrada()

    if houve_novidades(resultados):
        carregar_tudo.clear()

    # O recibo fica no ecrã o resto da sessão. Quem larga um ficheiro
    # precisa de o ver confirmado, e não só no instante em que acontece:
    # o Streamlit reexecuta a página a cada clique.
    #
    # Guardado por (ficheiro, estado) e não numa lista: um ficheiro que
    # fica em espera é reavaliado a cada clique, e numa lista a mesma
    # mensagem empilhava-se até encher o ecrã.
    recibos = st.session_state.setdefault("entrada", {})
    for r in resultados:
        recibos[(r.ficheiro, r.estado)] = r

for r in st.session_state.get("entrada", {}).values():
    caixa = {
        "ingerido": st.success,
        "repetido": st.info,
        "adiado": st.info,
        "problema": st.warning,
        "aviso": st.warning,
    }[r.estado]

    # Só o primeiro parágrafo. A recusa de um relatório traz a lista de
    # colunas em falta atrás, que é o que resolve o problema mas não o
    # que se quer ler no topo do painel — isso fica no .txt, ao lado do
    # ficheiro, para quem for lá ver.
    resumo = r.mensagem.split("\n\n")[0].replace("\n", " ")
    if r.estado == "problema":
        resumo += (
            " O ficheiro e a explicação completa ficaram em "
            "`data/entrada/com problemas`."
        )
    caixa(f"**{r.ficheiro}** — {resumo}")


dados = carregar_tudo()
tabela = dados["tabela"]

# Meses oferecidos no seletor. Os anteriores continuam na tabela — são
# precisos como termo de comparação homólogo e aparecem nos gráficos.
meses_disponiveis = [m for m in tabela.index if m >= str(MES_INICIO_VISIVEL)]


# --------------------------------------------------------------------- barra lateral

with st.sidebar:
    st.markdown("### o ginásio")
    st.caption("Dashboard de gestão · em desenvolvimento")

    st.divider()

    dias_desde_export = (date.today() - dados["data_snapshot"]).days
    st.markdown("**Dados carregados**")
    st.markdown(
        f"Última exportação: **{dados['data_snapshot'].strftime('%d-%m-%Y')}**  \n"
        f"({dias_desde_export} dias atrás)"
    )

    # Em demonstração o aviso não se aplica: as datas são simuladas e a
    # base é estática, portanto envelhece sempre. Dizer "os dados têm 200
    # dias" sobre dados inventados alarma sem informar.
    if e_demo():
        st.caption(
            "Datas simuladas — geradas a partir da data em que a base "
            "de demonstração foi criada."
        )
    elif dias_desde_export > DIAS_ATE_AVISO:
        st.warning(
            f"Os dados têm {dias_desde_export} dias. Os números abaixo "
            "refletem o ginásio à data da última exportação, não hoje. "
            "Uma nova exportação do software de gestão atualiza tudo."
        )

    if not e_demo():
        st.caption(
            "Para atualizar: arraste a exportação do software de gestão para a "
            "pasta **data/entrada** e volte a abrir o painel."
        )

        # Uma cópia de segurança que falha sem ninguém ver é o modo de
        # falha clássico — por isso a data fica sempre à vista.
        if pasta_nuvem() is None:
            st.caption("Cópias de segurança: só neste computador.")
        else:
            copia = ultima_copia_na_nuvem()
            if copia is None:
                st.caption(
                    "Cópia de segurança na nuvem: ainda nenhuma. É feita "
                    "sozinha a cada exportação nova."
                )
            # Mais antiga que os dados = a última exportação não foi
            # copiada. Velha mas a acompanhar os dados não é problema: o
            # aviso de dados antigos, acima, já cobre esse caso.
            elif copia < dados["data_snapshot"]:
                st.warning(
                    f"A última cópia de segurança na nuvem é de {copia:%d-%m-%Y} "
                    "e não inclui a exportação mais recente."
                )
            else:
                st.caption(f"Cópia de segurança na nuvem: {copia:%d-%m-%Y}.")

    st.divider()
    st.markdown("**Mês em análise**")
    mes_escolhido = st.selectbox(
        "Escolha o mês",
        options=meses_disponiveis,
        index=len(meses_disponiveis) - 1,
        format_func=rotulo_mes,
        label_visibility="collapsed",
    )
    legenda_meses = (
        f"Pode escolher de {rotulo_mes(meses_disponiveis[0])} a "
        f"{rotulo_mes(meses_disponiveis[-1])} — todos têm mês homólogo para "
        "comparar."
    )
    # Só quando a exportação parou a meio do mês. Se fechou o mês, ele
    # está no seletor, e dizer que "fica de fora" contradizia o ecrã.
    if dados["mes_fim"] < dados["mes_snapshot"]:
        legenda_meses += (
            f" O mês da exportação ({rotulo_mes(dados['mes_snapshot'])}) "
            "fica de fora por estar incompleto."
        )
    st.caption(legenda_meses)


# --------------------------------------------------------------------- separadores

tab_geral, tab_receita, tab_retencao, tab_renovacoes, tab_dados = st.tabs(
    ["Visão Geral", "Receita", "Retenção", "Renovações", "Dados"]
)


# ----------------------------------------------------------------- Visão Geral

with tab_geral:
    st.markdown(f"## Como está o ginásio em {rotulo_mes(mes_escolhido)}")

    atual, anterior = valores_do_mes(tabela, mes_escolhido)
    homologo = mes_homologo(mes_escolhido)

    if anterior is not None:
        st.caption(
            f"A variação por baixo de cada número compara com "
            f"**{rotulo_mes(homologo)}** — o mesmo mês do ano passado."
        )
    else:
        st.caption(
            f"Sem {rotulo_mes(homologo)} no histórico — não há termo de "
            "comparação homólogo para este mês."
        )

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(
        "Sócias ativas",
        f"{int(atual['ativas'])}",
        delta_numero(atual["ativas"], anterior["ativas"] if anterior is not None else None),
    )
    c2.metric(
        "Faturação",
        formatar_euros(atual["faturacao"]),
        delta_numero(atual["faturacao"], anterior["faturacao"] if anterior is not None else None, " €"),
    )
    c3.metric(
        "Receita recorrente",
        formatar_euros(atual["mrr"]),
        delta_numero(atual["mrr"], anterior["mrr"] if anterior is not None else None, " €"),
    )
    c4.metric(
        "Receita por sócia",
        f"€{atual['arpu']:.0f}",
        delta_numero(atual["arpu"], anterior["arpu"] if anterior is not None else None, " €"),
    )
    # Média de 3 meses e não o mês: o valor mensal oscila entre 6% e 12%
    # sem que nada mude no ginásio, e o cartão punha a conversa em cima
    # desse ruído. "Saídas" e não "Cancelamentos": conta quem deixou de
    # ter plano pago, incluindo quem falha um mês e volta — não os
    # cancelamentos registados no software de gestão.
    c5.metric(
        "Saídas · média 3 meses",
        formatar_pct(atual["saidas_3m_pct"]),
        delta_pontos(
            atual["saidas_3m_pct"],
            anterior["saidas_3m_pct"] if anterior is not None else None,
        ),
        delta_color="inverse",  # descer é bom
        help=(
            "Sócias que tinham plano pago no mês anterior e deixaram de ter, "
            "a dividir pelas sócias do mês anterior — somado nos últimos 3 "
            "meses. Não são os cancelamentos registados no software de gestão: "
            "inclui quem falha um mês e volta."
        ),
    )

    linha_fluxo = (
        f"Entraram **{int(atual['novos'])}** sócias e saíram "
        f"**{int(atual['perdidos'])}** em {rotulo_mes(mes_escolhido)} "
        f"({formatar_pct(atual['churn_pct'])} das sócias do mês anterior)."
    )
    if anterior is not None:
        linha_fluxo += (
            f" Em {rotulo_mes(homologo)} tinham entrado {int(anterior['novos'])} "
            f"e saído {int(anterior['perdidos'])}."
        )
    st.caption(linha_fluxo)

    st.divider()
    st.markdown("### Evolução mês a mês")
    st.caption("Histórico completo, incluindo os anos que servem de comparação.")

    # A tabela é mais longa do que a lista de meses selecionáveis: os anos
    # mais antigos entram nos gráficos como contexto.
    x = list(tabela.index)
    g1, g2 = st.columns(2)
    with g1:
        st.plotly_chart(
            grafico_linha(
                x, tabela["ativas"].tolist(), "Sócias ativas", COR_ROSE,
                "<b>%{x}</b><br>Sócias: %{y}<extra></extra>",
            ),
            width="stretch",
        )
        st.plotly_chart(
            grafico_novos_perdidos(
                x, tabela["novos"].tolist(), tabela["perdidos"].tolist(),
                "Entradas e saídas",
            ),
            width="stretch",
        )
    with g2:
        st.plotly_chart(
            grafico_linha(
                x, tabela["mrr"].tolist(), "Receita recorrente (MRR)", COR_BLUE,
                "<b>%{x}</b><br>MRR: €%{y:,.0f}<extra></extra>",
            ),
            width="stretch",
        )
        st.plotly_chart(
            grafico_linha(
                x, tabela["saidas_3m_pct"].tolist(), "Saídas · média 3 meses (%)", COR_RED,
                "<b>%{x}</b><br>Saídas (3 meses): %{y:.1f}%%<extra></extra>",
            ),
            width="stretch",
        )

    # Acumulado do ano do mês escolhido, de Janeiro até esse mês —
    # escolher Dezembro dá o ano inteiro. Ver historico.kpis_ano_ate.
    acumulado = kpis_ano_ate(tabela, mes_escolhido)
    ano = mes_escolhido[:4]
    primeiro = NOMES_MESES[int(acumulado["inicio"][5:]) - 1]
    periodo = (
        rotulo_mes(acumulado["fim"]) if acumulado["inicio"] == acumulado["fim"]
        else f"{primeiro} a {rotulo_mes(acumulado['fim'])}"
    )

    st.divider()
    st.markdown(f"### Acumulado de {ano}")
    st.caption(f"{periodo}.")

    p1, p2, p3, p4 = st.columns(4)
    p1.metric(
        "Crescimento de sócias",
        f"{acumulado['crescimento_socias_pct']:+.0f}%",
        help=f"Sócias ativas em {rotulo_mes(acumulado['fim'])} contra Dezembro de {int(ano) - 1}.",
    )
    p2.metric("Faturação acumulada", formatar_euros(acumulado["faturacao_total"]))
    p3.metric("Novas sócias", f"{acumulado['total_novos']}")
    p4.metric(
        "Saídas por mês (média)",
        formatar_pct(acumulado["saidas_pct"]),
        help="Saídas do período a dividir pelas sócias no início de cada mês.",
    )


# -------------------------------------------------------------------- Receita

with tab_receita:
    st.markdown("## De onde vem a faturação")
    st.caption(
        "As mesmas contas do cartão *Faturação*: sem IVA, sem pagamentos "
        "anulados, e cada pagamento no mês de serviço a que diz respeito — "
        "um bloco de 3 meses conta um terço em cada mês."
    )

    # Todos os meses da tabela e não só os do seletor da barra lateral:
    # aqui não há comparação com o ano anterior, por isso 2023 também
    # serve. O mês incompleto da exportação fica de fora, como lá.
    meses_receita = list(tabela.index)
    inicio_do_ano = f"{meses_receita[-1][:4]}-01"
    de, ate = st.select_slider(
        "Período",
        options=meses_receita,
        value=(
            inicio_do_ano if inicio_do_ano in meses_receita else meses_receita[0],
            meses_receita[-1],
        ),
        format_func=rotulo_mes,
    )

    receita = dados["receita"]
    areas = por_area(receita, de, ate)

    if areas.empty:
        st.info("Não há faturação registada neste período.")
    else:
        st.metric(
            f"Faturação · {rotulo_periodo(de, ate)}",
            formatar_euros(areas["euros"].sum()),
        )

        st.plotly_chart(
            grafico_distribuicao(
                areas["area"].tolist(), areas["euros"].tolist(),
                areas["pct"].tolist(), "Por área", COR_ROSE_FORTE,
            ),
            width="stretch",
        )
        st.dataframe(
            pd.DataFrame({
                "Área": areas["area"],
                "Faturação": areas["euros"].map(formatar_euros),
                "% do total": areas["pct"].map(formatar_pct),
            }),
            width="stretch",
            hide_index=True,
        )

        st.divider()
        st.markdown("### Por plano")

        opcoes = areas["area"].tolist()
        area = st.selectbox(
            "Área",
            options=opcoes,
            index=opcoes.index("Mensalidades") if "Mensalidades" in opcoes else 0,
        )
        planos = detalhe(receita, area, de, ate)

        st.plotly_chart(
            grafico_distribuicao(
                planos["item"].tolist(), planos["euros"].tolist(),
                planos["pct_area"].tolist(), f"{area} — % da área",
                COR_ROSE_FORTE,
            ),
            width="stretch",
        )
        st.dataframe(
            pd.DataFrame({
                "Plano": planos["item"],
                "Faturação": planos["euros"].map(formatar_euros),
                "% da área": planos["pct_area"].map(formatar_pct),
                "% do total": planos["pct_total"].map(formatar_pct),
            }),
            width="stretch",
            hide_index=True,
        )
        st.caption(
            "Os planos com e sem «25» no nome — a tabela de preços nova e a "
            "antiga — aparecem juntos. Taxas de congelamento, multas e "
            "acertos ficam numa linha só. Na loja e em *Outros*, o detalhe é "
            "pela família do software de gestão (na loja, a marca)."
        )

        # O período todo, todas as áreas — para quem quiser trabalhar os
        # números numa folha de cálculo.
        completo = pd.concat(
            [detalhe(receita, a, de, ate).assign(area=a) for a in opcoes]
        )
        st.download_button(
            "Descarregar o período em CSV",
            data=(
                completo[["area", "item", "euros", "pct_area", "pct_total"]]
                .round(2)
                .rename(columns={
                    "area": "Área", "item": "Plano", "euros": "Faturação (€)",
                    "pct_area": "% da área", "pct_total": "% do total",
                })
                .to_csv(index=False)
                .encode("utf-8-sig")
            ),
            file_name=f"faturacao_{de}_a_{ate}.csv",
            mime="text/csv",
        )


# ------------------------------------------------------------------- Retenção

with tab_retencao:
    st.markdown("## Sócias sem vir ao ginásio")
    st.caption(
        "Sócias com mensalidade presencial ativa e 30 dias ou mais sem passar "
        "no torniquete, ou sem nenhuma entrada registada."
    )

    risco = dados["risco"]

    if risco.empty:
        st.info("Sem dados de presenças suficientes para calcular esta lista.")
    else:
        contagem = risco["flag"].value_counts()
        ordem = ["risco", "sem presença no periodo"]
        rotulos = {
            "risco": "30 dias ou mais sem vir",
            "sem presença no periodo": "Sem qualquer entrada",
        }

        r1, r2 = st.columns(2)
        for col, flag in zip((r1, r2), ordem):
            col.metric(rotulos[flag], int(contagem.get(flag, 0)))

        # Só definições e limites dos dados. A razão dos 30 dias (medida
        # nos dados, ver presencas_kpis.socias_em_risco) não fica no
        # painel: é explicada à gerência em pessoa, e o painel mostra os
        # números para ela tirar as conclusões dela.
        st.markdown(
            "- A contagem de dias é feita a partir da **última presença "
            "registada nos dados**, não a partir de hoje.\n"
            "- *Sem qualquer entrada*: nunca passaram no torniquete desde "
            "Janeiro de 2026.\n"
            "- A coluna *Personal Trainer* assinala sócias com PT, que podem "
            "vir ao ginásio sem passar no torniquete.\n"
            "- Ficam de fora os planos online, as sócias suspensas e as "
            "inscritas há menos de 30 dias."
        )

        st.divider()

        filtro = st.multiselect(
            "Mostrar",
            options=[rotulos[f] for f in ordem if f in contagem.index],
            default=[rotulos[f] for f in ordem if f in contagem.index],
        )
        inverso = {v: k for k, v in rotulos.items()}
        flags_escolhidas = [inverso[r] for r in filtro]

        vista = risco[risco["flag"].isin(flags_escolhidas)].copy()
        vista = vista.sort_values("dias_ausente", ascending=False, na_position="last")

        st.markdown(f"**{len(vista)} sócias** nesta seleção.")
        st.dataframe(
            vista.assign(
                dias=vista["dias_ausente"].apply(
                    lambda v: "nunca veio" if pd.isna(v) else f"{int(v)} dias"
                ),
                ultima=vista["ultima_presenca"].dt.strftime("%d-%m-%Y").fillna("—"),
                flag=vista["flag"].map(rotulos),
                pt=vista["tem_PT"].map({True: "Sim", False: ""}),
            )[["nome", "dias", "ultima", "flag", "pt"]].rename(
                columns={
                    "nome": "Sócia",
                    "dias": "Sem vir há",
                    "ultima": "Última presença",
                    "flag": "Nível",
                    "pt": "Personal Trainer",
                }
            ),
            width="stretch",
            hide_index=True,
        )


# ----------------------------------------------------------------- Renovações

with tab_renovacoes:
    renovacoes = dados["renovacoes"]
    mes_alvo = dados["mes_snapshot"] + 1

    st.markdown(f"## Renovações — {rotulo_mes(mes_alvo)}")
    st.caption(
        "Sócias cuja fidelização ou bloco pré-pago termina no mês seguinte "
        "ao da última exportação."
    )

    if renovacoes.empty:
        st.info("Não há renovações previstas para este mês.")
    else:
        r1, r2, r3 = st.columns(3)
        r1.metric("Sócias na lista", len(renovacoes))
        if "tipo" in renovacoes.columns:
            por_tipo = renovacoes["tipo"].value_counts()
            for col, (tipo, n) in zip([r2, r3], por_tipo.items()):
                col.metric(str(tipo), int(n))

        st.divider()

        vista = renovacoes.copy()
        vista["valor"] = vista["valor"].apply(
            lambda v: f"€{v:.2f}" if pd.notna(v) else "—"
        )
        vista["data_fim"] = vista["data_fim"].dt.strftime("%d-%m-%Y")
        vista = vista[["nome", "gestor", "tipo", "plano", "valor", "data_fim", "motivo"]]
        vista.columns = ["Sócia", "Gestor", "Tipo", "Plano", "Valor",
                         "Termina em", "Motivo"]

        st.dataframe(vista, width="stretch", hide_index=True)

        st.download_button(
            "Descarregar lista em CSV",
            data=vista.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"renovacoes_{mes_alvo}.csv",
            mime="text/csv",
        )


# ---------------------------------------------------------------------- Dados

with tab_dados:
    st.markdown("## Os números por trás dos gráficos")
    st.caption("Uma linha por mês, para conferência.")

    # Pelo nome e não pela posição: uma coluna nova em kpis_mensais
    # desalinhava todos os rótulos sem dar erro.
    vista = tabela.rename(columns={
        "ativas": "Sócias ativas",
        "novos": "Novas",
        "perdidos": "Saídas",
        "mrr": "Receita recorrente",
        "faturacao": "Faturação",
        "arpu": "Receita por sócia",
        "churn_pct": "Saídas %",
        "saidas_3m_pct": "Saídas % (média 3 meses)",
        "retencao_pct": "Retenção %",
        "ltv": "Valor de vida estimado",
        "renovacao_n": "Renovações no mês",
    })
    vista.index = [rotulo_mes(m) for m in vista.index]
    vista.index.name = "Mês"
    st.dataframe(vista, width="stretch")

    st.download_button(
        "Descarregar tabela em CSV",
        data=tabela.to_csv().encode("utf-8-sig"),
        file_name="kpis_mensais.csv",
        mime="text/csv",
    )

    st.divider()
    st.markdown("### Exportações já carregadas")
    st.dataframe(
        dados["snapshots"].rename(
            columns={
                # A partir do snapshot 2026-07-31 a data deixa de ser o dia
                # em que a equipa exportou e passa a ser o último mês completo
                # que o ficheiro cobre. Quando a exportação chegou fica em
                # _raw_snapshots.ingerido_em.
                "snapshot_data": "Exportação (mês)",
                "tabela": "Conteúdo",
                "n_linhas": "Linhas",
                "cobertura_de": "Cobre desde",
                "cobertura_ate": "Cobre até",
            }
        ),
        width="stretch",
        hide_index=True,
    )

    st.divider()
    st.markdown("### Comparar com o software de gestão")
    estados = dados["estados"]
    st.markdown(
        f"Na última exportação de pagamentos, o software de gestão dava "
        f"**{estados.get('A', 0)} sócias ativas** e "
        f"**{estados.get('S', 0)} suspensas**. As listas de Retenção e "
        "Renovações partem destes estados."
    )
    st.caption(
        f"O software de gestão pode mostrar mais ativas: há **{dados['a_sem_pagamentos']}** "
        "sócias marcadas como ativas sem nenhum pagamento na última exportação, "
        "e essas o painel não conta. O cartão *Sócias ativas* da Visão Geral "
        "responde a outra pergunta — quem teve um plano pago nesse mês — e "
        "por isso também não coincide: inclui suspensas que pagaram a taxa de "
        "congelamento e sócias que entretanto cancelaram."
    )

    st.divider()
    st.markdown("### Notas sobre os números")
    st.markdown(
        "- **Saídas:** o cartão da Visão Geral soma os últimos 3 meses; o "
        "valor de cada mês sozinho está na coluna *Saídas %*.\n"
        "- **Valor de vida estimado** é calculado a partir das saídas de um "
        "só mês — é uma estimativa, não um valor medido.\n"
        "- **Receita por sócia** inclui receita de quem não conta como sócia "
        "ativa (por exemplo, avaliações ou nutrição compradas avulso)."
    )
