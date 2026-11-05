"""
Gera uma base de dados de demonstração, com sócias e valores inventados.

Serve dois propósitos:

1. **Desenvolver noutra máquina** sem levar dados pessoais reais. O
   portátil clona o repositório, corre este script, e tem um sistema
   completo para trabalhar.
2. **Mostrar o projeto publicamente** (portefólio) sem expor ninguém.

A estrutura é idêntica à real — mesmas tabelas, mesmas colunas, mesmas
regras de negócio — e a trajetória de sócias segue de perto a do ginásio,
para que os gráficos e as listas tenham um aspeto plausível. Os nomes,
porém, são gerados a partir de listas de nomes comuns e não correspondem
a ninguém.

Uso:
    python scripts/gerar_dados_demo.py
    python scripts/gerar_dados_demo.py --destino data/outra.sqlite --forcar

Por segurança, recusa escrever por cima de um ficheiro existente sem
--forcar, e recusa sempre escrever num ficheiro cujo nome não contenha
"demo" (é isso que impede um engano em cima da base de dados real).
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))

from src.db import criar_schema, conectar  # noqa: E402

# Semente fixa: correr duas vezes com o mesmo fim dá exatamente a mesma
# base de dados.
SEMENTE = 20260803

# Trajetória de sócias ativas a imitar, em meses ANTES do fim dos dados.
# O resto interpola-se.
#
# Duas razões para ser relativa e não um calendário fixo:
#
# 1. Assim os dados acompanham a data em que se gera. Com datas fixas, a
#    demonstração envelhecia e o painel avisava que os dados estavam
#    velhos — má primeira impressão para quem abre o link.
# 2. A versão anterior usava a curva real do cliente. Não identifica
#    ninguém, mas é a trajetória de um negócio real, e a promessa de
#    "dados inteiramente fictícios" tem de ser verdadeira até aqui. Estes
#    números são inventados: mesma forma plausível (queda, recuperação,
#    crescimento), escala e inflexões diferentes.
ANCORAS_RELATIVAS = {
    -48: 312, -40: 285, -34: 268, -28: 279,
    -22: 301, -16: 348, -10: 397, -4: 441, 0: 452,
}

# Quantos meses de presenças gerar. As exportações de acessos cobrem uma
# janela móvel, não o histórico todo.
MESES_DE_PRESENCAS = 6


def _fim_do_ultimo_mes_completo(hoje: date) -> date:
    """
    Último dia do mês mais recente que já fechou.

    O painel só mostra um mês quando a cobertura chega ao fim dele (ver
    `ultimo_mes_fechado` em src/historico.py). Gerar dados que acabam a
    meio de um mês faria a demonstração esconder esse mês sem razão
    aparente.
    """
    if (hoje + timedelta(days=1)).month != hoje.month:
        return hoje  # hoje já é o último dia do mês
    return hoje.replace(day=1) - timedelta(days=1)

PRIMEIROS = [
    "Maria", "Ana", "Sofia", "Beatriz", "Carolina", "Inês", "Mariana",
    "Rita", "Joana", "Catarina", "Marta", "Helena", "Teresa", "Cláudia",
    "Patrícia", "Sandra", "Susana", "Vera", "gerente", "Filipa", "Raquel",
    "Alexandra", "Cristina", "Luísa", "Paula", "Isabel", "Margarida",
    "Alexandra", "Bárbara", "Daniela", "Elisabete", "Fernanda", "Gabriela",
    "Irene", "Júlia", "Laura", "Matilde", "Nádia", "Olga", "Pilar",
    "Rosa", "Sara", "Tânia", "Vanessa", "Xana", "Zélia", "Carla", "Emília",
]

APELIDOS = [
    "Silva", "Santos", "Ferreira", "Pereira", "Oliveira", "Costa", "Rodrigues",
    "Martins", "Jesus", "Sousa", "Fernandes", "Gonçalves", "Gomes", "Lopes",
    "Marques", "Alves", "Almeida", "Ribeiro", "Pinto", "Carvalho", "Teixeira",
    "Moreira", "Correia", "Mendes", "Nunes", "Soares", "Vieira", "Monteiro",
    "Cardoso", "Rocha", "Neves", "Coelho", "Cruz", "Cunha", "Pires", "Ramos",
]

# (descrição do plano, família, mensalidade, meses cobertos por pagamento)
PLANOS = [
    ("Plano GINÁSIO Mensal", "Mensalidades", 42.90, 1),
    ("Plano GINÁSIO Trimestral", "Mensalidades", 38.90, 3),
    ("Plano GINÁSIO Semestral", "Mensalidades", 35.90, 6),
    ("Plano GINÁSIO Anual", "Mensalidades", 32.90, 12),
    ("Plano GINÁSIO Kids", "kids", 29.50, 1),
]
PESOS_PLANOS = [0.55, 0.20, 0.12, 0.08, 0.05]

GESTORAS = ["gerente", "Sónia", "Rita", "Marlene"]

ARTIGOS_LOJA = [
    ("Barra proteica", "Loja", 2.50),
    ("Bebida isotónica", "Loja", 1.80),
    ("T-shirt GINÁSIO", "Loja", 18.00),
    ("Aluguer de cacifo", "Cacifos", 8.00),
]


def _meses(inicio: date, fim: date) -> list[date]:
    """Lista do primeiro dia de cada mês entre inicio e fim (inclusive)."""
    out, ano, mes = [], inicio.year, inicio.month
    while (ano, mes) <= (fim.year, fim.month):
        out.append(date(ano, mes, 1))
        mes += 1
        if mes == 13:
            ano, mes = ano + 1, 1
    return out


def _alvo_por_mes(meses: list[date], fim: date) -> dict[date, int]:
    """Interpola linearmente as âncoras para obter um alvo por mês."""
    pontos = sorted(
        (_somar_meses(fim.replace(day=1), desvio), valor)
        for desvio, valor in ANCORAS_RELATIVAS.items()
    )

    alvos = {}
    for m in meses:
        if m <= pontos[0][0]:
            alvos[m] = pontos[0][1]
            continue
        if m >= pontos[-1][0]:
            alvos[m] = pontos[-1][1]
            continue
        for (d1, v1), (d2, v2) in zip(pontos, pontos[1:]):
            if d1 <= m <= d2:
                total = (d2.year - d1.year) * 12 + (d2.month - d1.month)
                passo = (m.year - d1.year) * 12 + (m.month - d1.month)
                alvos[m] = round(v1 + (v2 - v1) * passo / total)
                break
    return alvos


def _somar_meses(d: date, n: int) -> date:
    ano = d.year + (d.month - 1 + n) // 12
    mes = (d.month - 1 + n) % 12 + 1
    return date(ano, mes, 1)


def gerar(
    destino: Path, forcar: bool = False, snapshot: date | None = None
) -> None:
    if "demo" not in destino.name.lower():
        raise SystemExit(
            f"Recusado: '{destino.name}' não contém 'demo' no nome. "
            "É a salvaguarda que impede escrever por cima da base de dados real."
        )
    if destino.exists() and not forcar:
        raise SystemExit(f"'{destino}' já existe. Use --forcar para substituir.")
    if destino.exists():
        destino.unlink()

    SNAPSHOT = snapshot or _fim_do_ultimo_mes_completo(date.today())

    rnd = random.Random(SEMENTE)
    primeiro = _somar_meses(SNAPSHOT.replace(day=1), min(ANCORAS_RELATIVAS))
    meses = _meses(primeiro, SNAPSHOT.replace(day=1))
    alvos = _alvo_por_mes(meses, SNAPSHOT)

    # ---------------------------------------------------------------- sócias
    # Simula entradas e saídas mês a mês até bater o alvo de cada mês.
    socias: dict[int, dict] = {}
    ativas: set[int] = set()
    proximo_id = 1000

    for m in meses:
        # saídas: churn mensal com pico no verão e em Fevereiro/Março
        base_churn = 0.075
        if m.month in (6, 7, 8):
            base_churn = 0.105
        elif m.month in (2, 3):
            base_churn = 0.09
        elif m.month == 1:
            base_churn = 0.05

        for sid in [s for s in ativas if rnd.random() < base_churn]:
            ativas.discard(sid)
            socias[sid]["saida"] = m

        # entradas: as necessárias para atingir o alvo do mês
        for _ in range(max(0, alvos[m] - len(ativas))):
            proximo_id += 1
            descricao, familia, valor, bloco = rnd.choices(PLANOS, PESOS_PLANOS)[0]
            socias[proximo_id] = {
                "nome": f"{rnd.choice(PRIMEIROS)} {rnd.choice(APELIDOS)}",
                "entrada": m,
                "saida": None,
                "plano": descricao,
                "familia": familia,
                "valor": valor,
                "bloco": bloco,
                "gestora": rnd.choice(GESTORAS),
                "tipo": rnd.choices(["Individual", "Família"], [0.85, 0.15])[0],
            }
            ativas.add(proximo_id)

    # ------------------------------------------------------------ pagamentos
    linhas: list[tuple] = []
    no_parcela = 0

    def juntar(sid, dados, pag_data, mes_servico, descricao, familia, valor,
               anulado="Não"):
        nonlocal no_parcela
        no_parcela += 1
        ativa_agora = dados["saida"] is None
        linhas.append((
            no_parcela,                                    # no_parcela
            100000 + no_parcela // 3,                      # pag_no_pag
            pag_data.isoformat(),                          # pag_data
            anulado,                                       # pag_anulado
            None,                                          # pag_data_anulacao
            mes_servico.isoformat(),                       # parcelas_disponivel
            descricao,                                     # parcelas_descricao
            round(valor, 2),                               # parcelas_valor_liquido
            "Nenhuma",                                     # parcelas_promocoes
            familia,                                       # inv_familia
            descricao,                                     # inv_descricao
            sid,                                           # utente_no_insc
            "A" if ativa_agora else rnd.choice(["M", "S"]),  # utente_status
            dados["entrada"].isoformat(),                  # utente_data_insc
            dados["nome"],                                 # doc_nome
            dados["gestora"],                              # utente_gestor
            dados["tipo"],                                 # utente_tipo_socio
            rnd.choice(["Multibanco", "Numerário", "Transferência"]),
            SNAPSHOT.isoformat(),                          # atualizado_em_snapshot
        ))

    for sid, d in socias.items():
        # taxa de inscrição — é daqui que sai o fim de fidelização
        juntar(sid, d, d["entrada"], d["entrada"],
               "Inscrição - 1º Pagamento", "", 25.00)

        fim = d["saida"] or _somar_meses(SNAPSHOT.replace(day=1), 1)
        mes = d["entrada"]
        while mes < fim:
            # um pagamento cobre `bloco` meses de serviço: uma linha por mês
            for i in range(d["bloco"]):
                servico = _somar_meses(mes, i)
                if servico >= fim:
                    break
                anulado = "Sim" if rnd.random() < 0.02 else "Não"
                # O dia de cobrança varia por sócia (na fonte real há
                # "Mensal dia 5", "Mensal dia 12", etc.), por isso os
                # pagamentos espalham-se pelo mês em vez de se juntarem
                # todos no dia 1. Nunca depois do fim dos dados.
                dia_pag = min(mes + timedelta(days=rnd.randint(0, 27)), SNAPSHOT)
                juntar(sid, d, dia_pag,
                       servico, d["plano"], d["familia"], d["valor"], anulado)
            mes = _somar_meses(mes, d["bloco"])

        # extras: PT, pack nutrição, loja — dão textura às famílias
        if rnd.random() < 0.18:
            for i in range(rnd.randint(1, 6)):
                servico = _somar_meses(d["entrada"], i)
                if servico >= fim:
                    break
                juntar(sid, d, servico, servico,
                       "Personal Trainer - 8 sessões", "Personal Trainer", 96.00)

        if rnd.random() < 0.10:
            servico = _somar_meses(d["entrada"], 1)
            if servico < fim:
                juntar(sid, d, servico, servico,
                       "Avaliação física", "Avaliações", 15.00)
                juntar(sid, d, servico, servico,
                       "Consulta de nutrição", "Nutrição", 30.00)

        for _ in range(rnd.randint(0, 3)):
            artigo, familia, valor = rnd.choice(ARTIGOS_LOJA)
            servico = _somar_meses(d["entrada"], rnd.randint(0, 8))
            if servico < fim:
                juntar(sid, d, servico, servico, artigo, familia, valor)

    # -------------------------------------------------------------- presenças
    # Janela móvel dos últimos meses, como nas exportações de acessos.
    presencas: list[tuple] = []
    fim_pres = SNAPSHOT
    inicio_pres = _somar_meses(SNAPSHOT.replace(day=1), -(MESES_DE_PRESENCAS - 1))
    turmas = ["Acesso Instalações", "Pilates", "Zumba", "Musculação", "Yoga"]

    ativas_hoje = [s for s, d in socias.items() if d["saida"] is None]
    for sid in ativas_hoje:
        perfil = rnd.choices(
            ["regular", "irregular", "parou", "ausente"],
            [0.58, 0.20, 0.12, 0.10],
        )[0]
        if perfil == "ausente":
            continue

        # quem "parou" deixa de aparecer algures pelo caminho
        limite = fim_pres
        if perfil == "parou":
            limite = inicio_pres + timedelta(
                days=rnd.randint(10, max(20, (fim_pres - inicio_pres).days - 30))
            )

        dia = inicio_pres
        prob = 0.42 if perfil == "regular" else 0.16
        while dia <= limite:
            if dia.weekday() < 6 and rnd.random() < prob:
                hora = f"{rnd.randint(7, 21):02d}:{rnd.choice(['00','15','30','45'])}:00"
                presencas.append((
                    sid, dia.isoformat(), hora, socias[sid]["nome"],
                    rnd.choice(turmas), socias[sid]["plano"], "A",
                    SNAPSHOT.isoformat(),
                ))
            dia += timedelta(days=1)

    # ------------------------------------------------------------------ gravar
    conn = conectar(destino)
    criar_schema(conn)

    conn.executemany(
        f"INSERT INTO _raw_pagamentos VALUES ({','.join('?' * 19)})", linhas
    )
    conn.executemany(
        f"INSERT OR IGNORE INTO _raw_presencas VALUES ({','.join('?' * 8)})",
        presencas,
    )
    conn.executemany(
        """INSERT INTO _raw_snapshots
           (snapshot_data, tabela, ficheiro_origem, hash_ficheiro, n_linhas,
            cobertura_de, cobertura_ate)
           VALUES (?,?,?,?,?,?,?)""",
        [
            (SNAPSHOT.isoformat(), "pagamentos", "DADOS FICTÍCIOS (demo)",
             "-", len(linhas), meses[0].isoformat(), SNAPSHOT.isoformat()),
            (SNAPSHOT.isoformat(), "presencas", "DADOS FICTÍCIOS (demo)",
             "-", len(presencas), inicio_pres.isoformat(), fim_pres.isoformat()),
        ],
    )
    conn.commit()
    conn.close()

    print(f"Base de dados de demonstração criada: {destino}")
    print(f"  {len(socias):>7,} sócias inventadas")
    print(f"  {len(linhas):>7,} linhas de pagamento")
    print(f"  {len(presencas):>7,} presenças")
    print(f"  {len(ativas_hoje):>7,} sócias ativas à data do snapshot simulado")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--destino", default="data/ginasio_demo.sqlite",
        help="caminho do ficheiro a criar (tem de conter 'demo' no nome)",
    )
    parser.add_argument(
        "--forcar", action="store_true", help="substituir se já existir"
    )
    parser.add_argument(
        "--fim",
        help="último dia dos dados (AAAA-MM-DD). Por omissão, o fim do "
             "último mês completo — assim a demonstração não envelhece.",
    )
    args = parser.parse_args()
    gerar(
        _RAIZ / args.destino,
        forcar=args.forcar,
        snapshot=date.fromisoformat(args.fim) if args.fim else None,
    )
