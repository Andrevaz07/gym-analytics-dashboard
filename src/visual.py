"""
Camada visual partilhada — paleta, gráficos Plotly e formatadores.

Todos os gráficos do painel saem daqui, para terem sempre as mesmas
cores. Quem quiser mudar o aspecto muda aqui, num sítio só.

Paleta: bege com acento rosa da marca, fonte Outfit + JetBrains Mono.
"""
from __future__ import annotations

import plotly.graph_objects as go

# --------------------------------------------------------------------- paleta

COR_BG = "#faf9f7"
COR_SURFACE = "#ffffff"
COR_ACCENT = "#202020"
COR_ROSE = "#c3949e"
COR_GREEN = "#058246"
COR_RED = "#c0392b"
COR_BLUE = "#5b8fa8"
COR_MUTED = "#7a7670"
COR_BORDER = "#ede9e4"
# O rosa da marca em barras grossas não chega: 2,5:1 contra o branco e quase
# cinzento. Este é o mesmo tom, mais carregado — passa os 3:1 e o mínimo de
# saturação (verificado com o validador de paletas, 27-10-2026).
COR_ROSE_FORTE = "#a85a6c"


# --------------------------------------------------------------------- formatadores


def formatar_euros(x: float) -> str:
    """€12 345 — separador de milhares em espaço, à portuguesa."""
    return f"€{x:,.0f}".replace(",", " ")


def formatar_pct(x: float) -> str:
    return f"{x:.1f}%"


# --------------------------------------------------------------------- gráficos


def _layout_base(titulo: str) -> dict:
    """Layout comum aos gráficos — paleta + tipografia consistentes."""
    return dict(
        title=dict(
            text=titulo,
            font=dict(family="Outfit, sans-serif", size=18, color=COR_ACCENT),
            x=0.0,
            xanchor="left",
        ),
        font=dict(family="Outfit, sans-serif", color=COR_ACCENT, size=12),
        paper_bgcolor=COR_SURFACE,
        plot_bgcolor=COR_SURFACE,
        margin=dict(t=60, b=40, l=60, r=20),
        height=340,
        hoverlabel=dict(font_family="JetBrains Mono"),
        xaxis=dict(
            showgrid=False,
            tickfont=dict(family="JetBrains Mono", size=11),
            linecolor=COR_BORDER,
        ),
        yaxis=dict(
            gridcolor=COR_BORDER,
            tickfont=dict(family="JetBrains Mono", size=11),
            zeroline=False,
        ),
        showlegend=False,
    )


def grafico_linha(x, y, titulo, cor, hover_fmt) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x, y=y, mode="lines+markers",
            line=dict(color=cor, width=3),
            marker=dict(size=8, color=cor, line=dict(width=2, color=COR_SURFACE)),
            hovertemplate=hover_fmt,
        )
    )
    fig.update_layout(**_layout_base(titulo))
    return fig


def grafico_novos_perdidos(x, novos, perdidos, titulo) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x, y=novos, name="Novas",
        marker_color=COR_GREEN, marker_line_width=0,
        hovertemplate="<b>%{x}</b><br>Novas: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=x, y=perdidos, name="Perdidas",
        marker_color=COR_RED, marker_line_width=0,
        hovertemplate="<b>%{x}</b><br>Perdidas: %{y}<extra></extra>",
    ))
    layout = _layout_base(titulo)
    layout["barmode"] = "group"
    layout["showlegend"] = True
    layout["legend"] = dict(
        orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0,
        font=dict(family="JetBrains Mono", size=11),
    )
    fig.update_layout(**layout)
    return fig


def grafico_distribuicao(categorias, euros, pct, titulo, cor) -> go.Figure:
    """
    Repartição de um total — a maior barra em cima, a percentagem na ponta
    de cada uma e os euros ao passar o rato.

    Sem eixo dos valores: a percentagem já está escrita em cada barra, e a
    tabela por baixo do gráfico tem os euros.
    """
    rotulos = [formatar_pct(p) for p in pct]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=euros, y=categorias, orientation="h",
            marker=dict(color=cor, line=dict(width=0), cornerradius=4),
            text=rotulos, textposition="outside", cliponaxis=False,
            textfont=dict(family="JetBrains Mono", size=11, color=COR_ACCENT),
            hovertemplate="<b>%{y}</b><br>€%{x:,.0f} · %{text}<extra></extra>",
        )
    )
    layout = _layout_base(titulo)
    # Altura pela quantidade de barras, para cada uma ficar com a mesma
    # espessura (~24 px) seja qual for a área escolhida no detalhe.
    layout["height"] = 90 + 38 * len(categorias)
    layout["bargap"] = 0.35
    layout["margin"] = dict(t=60, b=20, l=10, r=70)
    layout["xaxis"] = dict(visible=False, range=[0, max(euros, default=0) * 1.12])
    layout["yaxis"] = dict(
        autorange="reversed", showgrid=False, automargin=True, ticksuffix="  ",
        tickfont=dict(family="Outfit, sans-serif", size=13, color=COR_ACCENT),
    )
    fig.update_layout(**layout)
    return fig


def grafico_barras_horizontais(categorias, valores, titulo, cor, hover_fmt) -> go.Figure:
    """Barras horizontais — para rankings curtos (ex.: sócias por flag de risco)."""
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=valores, y=categorias, orientation="h",
            marker_color=cor, marker_line_width=0,
            hovertemplate=hover_fmt,
        )
    )
    layout = _layout_base(titulo)
    layout["xaxis"] = dict(
        showgrid=True, gridcolor=COR_BORDER,
        tickfont=dict(family="JetBrains Mono", size=11), zeroline=False,
    )
    layout["yaxis"] = dict(
        showgrid=False, tickfont=dict(family="JetBrains Mono", size=11),
        linecolor=COR_BORDER,
    )
    fig.update_layout(**layout)
    return fig
