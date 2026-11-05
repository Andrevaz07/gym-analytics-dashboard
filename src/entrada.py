"""
Ingestão por pasta: a gerente arrasta a extração para `data/entrada/` e
está feito. Sem botões, sem linha de comandos, sem renomear ficheiros.

O que acontece a cada ficheiro pousado na pasta:

  1. espera que a cópia termine (comparando o tamanho);
  2. reconhece o relatório pelas colunas — pagamentos ou acessos;
  3. tira a data do snapshot do próprio conteúdo (o último dia coberto),
     por isso o nome do ficheiro é irrelevante;
  4. faz cópia de segurança da BD antes de lhe tocar (ADR 0005);
  5. ingere, e arruma o ficheiro em `data/snapshots/` com o nome canónico.

Os passos 1-3 correm para todos os ficheiros antes de qualquer um
entrar, e os que passam entram da extração mais antiga para a mais
recente. Nos pagamentos a ordem decide o resultado: o UPSERT dá razão a
quem entra por último, e uma extração antiga a entrar depois de uma
recente repunha estados de sócia e desfazia anulações nas linhas em
comum. Pela mesma razão, uma extração de pagamentos que cubra menos do
que a última já carregada é recusada em vez de entrar.

O que não é reconhecido vai para `data/entrada/com problemas/` com um
`.txt` ao lado a dizer porquê. Nada fica em silêncio e nada se perde: o
ficheiro original está sempre algures, ou no arquivo ou nos problemas.

Corre de duas maneiras, com o mesmo resultado:
  - pelo lançador, antes do painel abrir (`python -m src.entrada`);
  - pelo próprio painel, a cada interação (custa um `iterdir` quando a
    pasta está vazia, que é o caso quase sempre).
"""
from __future__ import annotations

import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from src.db import conectar, criar_schema, e_demo
from src.ingest_common import hash_ficheiro
from src.ingest_pagamentos import ingest_pagamentos
from src.ingest_presencas import ingest_presencas
from src.ingestion import (
    COLUNAS_ESSENCIAIS_ACESSOS,
    COLUNAS_ESSENCIAIS_PAGAMENTOS,
    USECOLS_ACESSOS,
    USECOLS_PAGAMENTOS,
    _detetar_linha_cabecalho,
    load_acessos,
    load_pagamentos,
)

_RAIZ = Path(__file__).resolve().parent.parent

PASTA_ENTRADA = _RAIZ / "data" / "entrada"
PASTA_ARQUIVO = _RAIZ / "data" / "snapshots"
NOME_PROBLEMAS = "com problemas"

# Só .xlsx: é o que o software de gestão exporta e o que os loaders leem
# (openpyxl). Um .csv ou um .xls antigo tem de ser convertido primeiro —
# a mensagem de problema diz isso.
EXTENSAO_ACEITE = ".xlsx"

# Ficheiros que vivem na pasta de propósito e nunca são para processar.
IGNORAR = {".gitkeep", "leia-me.txt", "desktop.ini", "thumbs.db"}

# Um ficheiro grande arrastado de uma pen ou da rede aparece na pasta
# antes de estar todo lá. Medir o tamanho duas vezes evita ingerir meio
# ficheiro e mandá-lo para os problemas por "estar corrompido".
SEGUNDOS_ENTRE_MEDICOES = 1.0

# Cópias de segurança a guardar. Uma por dia de ingestão; a ingestão é
# mensal, por isso seis são mais de meio ano de recuo.
BACKUPS_A_MANTER = 6

# `presencas` é o nome da tabela; `acessos` é como o relatório se chama
# no software de gestão e como os ficheiros estão nomeados em data/snapshots.
NOME_NO_ARQUIVO = {"pagamentos": "pagamentos", "presencas": "acessos"}

INGESTORES = {"pagamentos": ingest_pagamentos, "presencas": ingest_presencas}


@dataclass
class Resultado:
    """O que aconteceu a um ficheiro. `estado` é o que a UI mostra."""

    ficheiro: str
    estado: str  # ingerido | repetido | problema | adiado | aviso
    mensagem: str
    tipo: str | None = None
    snapshot: date | None = None
    stats: dict = field(default_factory=dict)


# ------------------------------------------------------------- reconhecer


def ficheiros_pousados(pasta: Path = PASTA_ENTRADA) -> list[Path]:
    """
    Ficheiros à espera na pasta de entrada, por ordem alfabética.

    A ordem aqui é só para a lista sair estável. A ordem em que entram
    na base é outra — por data de cobertura, ver `processar_entrada`.
    """
    if not pasta.is_dir():
        return []
    return sorted(
        f
        for f in pasta.iterdir()
        if f.is_file()
        and not f.name.startswith(".")      # .DS_Store e afins
        and not f.name.startswith("~$")     # temporário do Excel aberto
        and f.name.lower() not in IGNORAR
    )


def _esta_completo(path: Path) -> bool:
    """True se o ficheiro parou de crescer — ou seja, a cópia acabou."""
    antes = path.stat().st_size
    if antes == 0:
        return False
    if SEGUNDOS_ENTRE_MEDICOES:
        time.sleep(SEGUNDOS_ENTRE_MEDICOES)
    return path.stat().st_size == antes


def identificar(path: Path) -> str:
    """
    Diz se o ficheiro é 'pagamentos' ou 'presencas', pelas colunas.

    O nome não conta para nada: o que o software de gestão escreve na caixa de
    diálogo é imprevisível, e as colunas são a única evidência fiável.

    Levanta ValueError com as duas razões quando não é nenhum dos dois —
    é aqui que se apanha o "Histórico dos documentos de facturação", o
    relatório errado que já veio uma vez e que passaria despercebido.
    """
    razoes = []
    for tipo, usecols, essenciais in (
        ("pagamentos", USECOLS_PAGAMENTOS, COLUNAS_ESSENCIAIS_PAGAMENTOS),
        ("presencas", USECOLS_ACESSOS, COLUNAS_ESSENCIAIS_ACESSOS),
    ):
        try:
            _detetar_linha_cabecalho(path, usecols, essenciais)
            return tipo
        except ValueError as erro:
            razoes.append(f"Não é o relatório de {tipo}:\n{erro}")

    raise ValueError(
        "Não reconheci este relatório.\n\n"
        "A causa mais provável é ser o relatório errado. O de pagamentos "
        "que serve é o das PARCELAS: reconhece-se porque tem colunas a "
        "começar por 'Parcelas ...' e 'Inv. ...'.\n\n"
        "Detalhe técnico:\n\n" + "\n\n".join(razoes)
    )


def data_de_cobertura(path: Path, tipo: str) -> date:
    """
    Último dia coberto pela extração — é essa a data do snapshot.

    Vem do conteúdo e não do nome do ficheiro, o que dá de graça a
    convenção acordada: uma extração que fecha Julho fica gravada como
    2026-07-31, seja qual for o dia em que a equipa a tirou.

    Custa uma leitura do ficheiro que o ingest a seguir volta a fazer.
    Sai caro em tempo de CPU e barato em complexidade, para uma operação
    que acontece uma vez por mês.
    """
    if tipo == "pagamentos":
        return load_pagamentos(path)["pag_data"].max().date()
    return load_acessos(path)["data"].max().date()


# ------------------------------------------------------------------ arrumar


def _destino_livre(destino: Path) -> Path:
    """`x.xlsx` -> `x-2.xlsx` -> `x-3.xlsx`... Nunca sobrepõe nada."""
    if not destino.exists():
        return destino
    n = 2
    while True:
        alternativa = destino.with_name(f"{destino.stem}-{n}{destino.suffix}")
        if not alternativa.exists():
            return alternativa
        n += 1


def _arquivar(path: Path, tipo: str, snapshot: date, arquivo: Path) -> Path:
    """Move para data/snapshots com o nome da convenção."""
    arquivo.mkdir(parents=True, exist_ok=True)
    nome = f"{snapshot:%Y-%m-%d}_{NOME_NO_ARQUIVO[tipo]}{path.suffix.lower()}"
    destino = _destino_livre(arquivo / nome)
    shutil.move(str(path), str(destino))
    return destino


def _por_de_lado(path: Path, motivo: str) -> Path:
    """
    Move para a subpasta de problemas e escreve a explicação ao lado.

    Sair da pasta de entrada é essencial: senão o mesmo ficheiro voltava
    a falhar a cada arranque do painel e a mensagem repetia-se para
    sempre. O `.txt` fica em português corrido porque quem o vai ler é a
    gerente, no Finder, sem ninguém ao lado.
    """
    problemas = path.parent / NOME_PROBLEMAS
    problemas.mkdir(parents=True, exist_ok=True)

    destino = _destino_livre(problemas / path.name)
    shutil.move(str(path), str(destino))
    destino.with_suffix(destino.suffix + ".txt").write_text(
        f"{path.name}\n"
        f"Posto de lado a {date.today():%d-%m-%Y}.\n\n"
        f"{motivo}\n",
        encoding="utf-8",
    )
    return destino


# ------------------------------------------------------------------- backup

_PADRAO_BACKUP = re.compile(r"\.bak-\d{4}-\d{2}-\d{2}$")


def _ficheiro_da_ligacao(conn: sqlite3.Connection) -> Path | None:
    """Caminho real da BD ligada. None se for em memória."""
    linha = conn.execute("PRAGMA database_list").fetchone()
    return Path(linha[2]) if linha and linha[2] else None


def copia_de_seguranca(conn: sqlite3.Connection) -> Path | None:
    """
    Copia a BD antes de a alterar, com VACUUM INTO (ADR 0005).

    VACUUM INTO lê a base consistente mesmo com a ligação aberta — ao
    contrário de copiar o ficheiro, que pode apanhar escritas a meio.

    Uma por dia: se a mesma extração for arrastada duas vezes no mesmo
    dia, guarda-se a primeira, que é a de antes de tudo. Devolve None se
    já existe a de hoje, e nunca impede a ingestão de acontecer.
    """
    origem = _ficheiro_da_ligacao(conn)
    if origem is None:
        return None

    destino = origem.with_name(f"{origem.name}.bak-{date.today():%Y-%m-%d}")
    if destino.exists():
        return None

    conn.commit()
    conn.execute("VACUUM INTO ?", (str(destino),))

    # Rotação: só apaga ficheiros que nós próprios criámos, com o nome
    # exacto do padrão, e só os mais antigos.
    antigos = sorted(
        f
        for f in origem.parent.glob(f"{origem.name}.bak-*")
        if _PADRAO_BACKUP.search(f.name)
    )
    for velho in antigos[:-BACKUPS_A_MANTER]:
        velho.unlink()

    return destino


_PADRAO_NUVEM = re.compile(r"^base-\d{4}-\d{2}-\d{2}\.sqlite$")


def pasta_nuvem() -> Path | None:
    """
    Pasta sincronizada para as cópias — iCloud, OneDrive, o que houver.

    Vem do `.env` (GINASIO_COPIAS_NUVEM). Sem ela, as cópias ficam só na
    máquina, como sempre ficaram.
    """
    valor = os.environ.get("GINASIO_COPIAS_NUVEM")
    return Path(valor).expanduser() if valor else None


def copia_para_a_nuvem(conn: sqlite3.Connection, pasta: Path | None = None) -> Path:
    """
    Copia a base, DEPOIS de uma ingestão, para a pasta sincronizada.

    A cópia de antes (`copia_de_seguranca`) serve para desfazer uma
    ingestão má e fica ao lado da base, no mesmo disco. Esta serve para o
    disco morrer: é a de depois, senão a extração mais recente nunca
    estava protegida.

    A base viva nunca vai para a pasta sincronizada (ADR 0005). O VACUUM
    INTO escreve num temporário local, e lá só aparece o ficheiro já
    acabado, por cópia para um nome provisório e troca de nome — o
    cliente de sincronização nunca vê um ficheiro a meio.

    Uma por dia: a segunda ingestão do dia substitui a primeira, porque é
    o estado mais recente que interessa. Seis guardadas.

    Levanta exceção se não conseguir — quem chama decide o que fazer com
    isso. Não cria a pasta-mãe: se o iCloud estiver desligado, criar o
    caminho à mão dava uma pasta que parece sincronizada e não é.
    """
    pasta = pasta or pasta_nuvem()
    origem = _ficheiro_da_ligacao(conn)
    if pasta is None or origem is None:
        raise ValueError("Sem pasta sincronizada configurada.")

    pasta.mkdir(exist_ok=True)

    temporario = origem.with_name(f"{origem.name}.nuvem-tmp")
    temporario.unlink(missing_ok=True)
    conn.commit()
    conn.execute("VACUUM INTO ?", (str(temporario),))

    destino = pasta / f"base-{date.today():%Y-%m-%d}.sqlite"
    parcial = destino.with_name(destino.name + ".parcial")
    try:
        shutil.copyfile(temporario, parcial)
        os.replace(parcial, destino)
    finally:
        temporario.unlink(missing_ok=True)

    antigas = sorted(f for f in pasta.iterdir() if _PADRAO_NUVEM.match(f.name))
    for velha in antigas[:-BACKUPS_A_MANTER]:
        velha.unlink()

    return destino


def ultima_copia_na_nuvem(pasta: Path | None = None) -> date | None:
    """Data da cópia mais recente na pasta sincronizada, se houver."""
    pasta = pasta or pasta_nuvem()
    if pasta is None or not pasta.is_dir():
        return None
    datas = sorted(f.name[5:15] for f in pasta.iterdir() if _PADRAO_NUVEM.match(f.name))
    return date.fromisoformat(datas[-1]) if datas else None


# ------------------------------------------------------------------ o ciclo


def _ja_ingerido(conn: sqlite3.Connection, hash_novo: str) -> str | None:
    """Data do snapshot que já tem este hash, se algum tiver."""
    linha = conn.execute(
        "SELECT snapshot_data FROM _raw_snapshots WHERE hash_ficheiro = ?",
        (hash_novo,),
    ).fetchone()
    return linha[0] if linha else None


def _ultima_cobertura(conn: sqlite3.Connection, tabela: str) -> date | None:
    """Data do snapshot mais recente já carregado nessa tabela."""
    linha = conn.execute(
        "SELECT MAX(snapshot_data) FROM _raw_snapshots WHERE tabela = ?",
        (tabela,),
    ).fetchone()
    return date.fromisoformat(linha[0][:10]) if linha and linha[0] else None


def _resultado_problema(path: Path, motivo: str, estado: str = "problema") -> Resultado:
    _por_de_lado(path, motivo)
    return Resultado(path.name, estado, motivo)


def _resultado_repetido(path: Path, ja: str) -> Resultado:
    return _resultado_problema(
        path,
        f"Este ficheiro já tinha entrado (extração de {ja}).\n"
        "Não é um erro e não se perdeu nada — podes apagá-lo.",
        estado="repetido",
    )


@dataclass
class _Reconhecido:
    """Ficheiro que passou as verificações e espera a sua vez de entrar."""

    path: Path
    hash: str
    tipo: str
    snapshot: date


def _reconhecer(path: Path, conn: sqlite3.Connection) -> Resultado | _Reconhecido:
    """
    Primeira fase: tudo o que se pode decidir sem tocar na base.

    Devolve um Resultado quando o ficheiro já tem destino (adiado, posto
    de lado, repetido) e um _Reconhecido quando está pronto a entrar.
    """
    if not _esta_completo(path):
        return Resultado(
            path.name,
            "adiado",
            "Ainda está a ser copiado. Fica para a próxima vez que o painel abrir.",
        )

    if path.suffix.lower() != EXTENSAO_ACEITE:
        return _resultado_problema(
            path,
            f"O painel só lê ficheiros {EXTENSAO_ACEITE}, e este é "
            f"'{path.suffix or 'sem extensão'}'.\n"
            "Abre-o no Excel e grava como .xlsx, ou pede a exportação nesse formato.",
        )

    hash_novo = hash_ficheiro(path)
    ja = _ja_ingerido(conn, hash_novo)
    if ja is not None:
        return _resultado_repetido(path, ja)

    try:
        tipo = identificar(path)
        snapshot = data_de_cobertura(path, tipo)
    except Exception as erro:
        return _resultado_problema(path, str(erro))

    return _Reconhecido(path, hash_novo, tipo, snapshot)


def _ingerir(r: _Reconhecido, conn: sqlite3.Connection, arquivo: Path) -> Resultado:
    """Segunda fase: backup, ingestão e arquivo de um ficheiro reconhecido."""
    # O hash volta a ser visto aqui porque a primeira fase correu antes
    # de qualquer ficheiro entrar: duas cópias do mesmo ficheiro largadas
    # juntas passam as duas por lá, e a segunda só se apanha agora.
    ja = _ja_ingerido(conn, r.hash)
    if ja is not None:
        return _resultado_repetido(r.path, ja)

    # Só nos pagamentos: as presenças entram com INSERT OR IGNORE, que
    # nunca altera uma linha que já exista, portanto a ordem não as afeta.
    # Igual à última não cai aqui — o ingest trata-o pelo hash.
    if r.tipo == "pagamentos":
        ultima = _ultima_cobertura(conn, "pagamentos")
        if ultima is not None and r.snapshot < ultima:
            return _resultado_problema(
                r.path,
                f"Esta extração de pagamentos chega só até {r.snapshot:%d-%m-%Y}, "
                f"e já entrou uma que chega até {ultima:%d-%m-%Y}. Não foi "
                "carregada, para não substituir informação recente por antiga.\n\n"
                "Se foi largada por engano, pode ser apagada. Se é mesmo para "
                "entrar, fala com quem mantém o painel antes de voltar a tentar.",
            )

    copia_de_seguranca(conn)

    try:
        stats = INGESTORES[r.tipo](r.path, r.snapshot, conn)
    except Exception as erro:
        return _resultado_problema(r.path, str(erro))

    destino = _arquivar(r.path, r.tipo, r.snapshot, arquivo)
    return Resultado(
        r.path.name,
        "ingerido",
        f"Entrou como extração de {r.snapshot:%d-%m-%Y} "
        f"e ficou guardado em {destino.name}.",
        tipo=r.tipo,
        snapshot=r.snapshot,
        stats=stats,
    )


def processar_entrada(
    conn: sqlite3.Connection | None = None,
    *,
    pasta: Path = PASTA_ENTRADA,
    arquivo: Path = PASTA_ARQUIVO,
) -> list[Resultado]:
    """
    Processa tudo o que estiver na pasta de entrada.

    Devolve lista vazia — sem sequer abrir a base de dados — quando não
    há nada, que é o caso em quase todas as chamadas: o painel chama
    isto a cada interação e não pode pagar por isso.

    Os ficheiros reconhecidos entram por data de cobertura, da mais
    antiga para a mais recente, e não pela ordem dos nomes. Os nomes
    enganam: o browser grava o segundo download como
    "Historico Parcelas (1).xlsx", que ordena ANTES do primeiro
    ("Historico Parcelas.xlsx") porque o espaço vem antes do ponto.
    """
    pousados = ficheiros_pousados(pasta)
    if not pousados:
        return []

    proprio = conn is None
    conn = conn or conectar()
    try:
        criar_schema(conn)  # idempotente; cobre a primeira utilização

        resultados: list[Resultado] = []
        prontos: list[_Reconhecido] = []
        for f in pousados:
            r = _reconhecer(f, conn)
            (prontos if isinstance(r, _Reconhecido) else resultados).append(r)

        prontos.sort(key=lambda r: (r.snapshot, r.path.name))
        resultados += [_ingerir(r, conn, arquivo) for r in prontos]

        # Uma cópia no fim, não uma por ficheiro: é o estado final que
        # interessa guardar fora da máquina.
        if houve_novidades(resultados) and pasta_nuvem() is not None:
            try:
                copia_para_a_nuvem(conn)
            except Exception as erro:
                resultados.append(Resultado(
                    "Cópia de segurança",
                    "aviso",
                    "Os dados novos entraram, mas a cópia para a pasta "
                    "sincronizada falhou — por agora só existem neste "
                    f"computador. Detalhe: {erro}",
                ))
        return resultados
    finally:
        if proprio:
            conn.close()


def houve_novidades(resultados: list[Resultado]) -> bool:
    """True se a base de dados mudou — logo, se há cache a deitar fora."""
    return any(r.estado == "ingerido" for r in resultados)


MARCAS = {"ingerido": "OK", "repetido": "--", "adiado": "..", "problema": "!!", "aviso": "!!"}


if __name__ == "__main__":
    # O painel já não processa a pasta em demonstração (dashboard.py), e
    # o lançador também não pode: uma extração real largada na pasta
    # entrava na base fictícia, misturada com sócias inventadas, e a base
    # real ficava sem ela. O risco ficou à vista quando a pasta do
    # portátil foi copiada inteira para o Mac da gerente, .env incluído.
    if e_demo():
        print(
            "  A base de dados em uso é a de demonstração (ver GINASIO_DB no .env).\n"
            "  A pasta data/entrada não é processada — as extrações ficam lá."
        )
        raise SystemExit(0)

    PASTA_ENTRADA.mkdir(parents=True, exist_ok=True)

    resultados = processar_entrada()
    if not resultados:
        print("  Sem extrações novas na pasta de entrada.")

    for r in resultados:
        print(f"  [{MARCAS[r.estado]}] {r.ficheiro}")
        for linha in r.mensagem.splitlines():
            print(f"       {linha}")
        if r.stats:
            print(f"       {r.stats}")
