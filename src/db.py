"""
Schema da BD do ginásio. Cria as tabelas raw + auditoria.

Ver docs/adr/0002,0003,0004 para o desenho.

"""

from __future__ import annotations
import os
from pathlib import Path
import sqlite3

from dotenv import load_dotenv

_RAIZ = Path(__file__).resolve().parent.parent

# Cada máquina define o seu caminho no .env (que não é versionado). Sem
# .env, usa a base de dados real — o comportamento de sempre.
load_dotenv(_RAIZ / ".env")

# Ancorado na raiz do projeto, não na pasta de onde se corre o comando.
# `conectar()` cria o ficheiro se não existir: com um caminho relativo,
# arrancar o dashboard da pasta errada criava uma BD vazia em silêncio,
# em vez de dar erro.
_ESCOLHIDO = os.environ.get("GINASIO_DB")
# Nesta versão pública só existem dados fictícios, por isso a
# omissão é a base de demonstração — um clone novo arranca a
# funcionar sem configuração nenhuma.
DB_PATH = (_RAIZ / _ESCOLHIDO) if _ESCOLHIDO else (_RAIZ / "data" / "ginasio_demo.sqlite")


def e_demo(caminho: Path | None = None) -> bool:
    """
    True quando a base de dados em uso é de demonstração.

    A convenção é o nome do ficheiro conter "demo" — a mesma regra que o
    gerador exige para escrever. Serve para o dashboard avisar em cima do
    ecrã que os números não são reais.
    """
    return "demo" in (caminho or DB_PATH).name.lower()


def demo_proibida(caminho: Path | None = None) -> bool:
    """
    True quando a base em uso é de demonstração numa máquina onde não pode.

    O lançador do Mac da gerente define GINASIO_PRODUCAO=1. Lá, a base
    fictícia nunca é a certa: se o painel arranca com ela, é porque veio
    um .env de outra máquina — aconteceu em Outubro de 2026, quando a
    pasta do portátil foi copiada inteira. A marca fica no lançador e não
    no .env por isso mesmo: é o .env que vem errado numa cópia, e o
    lançador vem sempre igual.
    """
    return e_demo(caminho) and os.environ.get("GINASIO_PRODUCAO") == "1"


def conectar(db_path = DB_PATH) -> sqlite3.Connection:
    """ Abre ligação à BD, criando o ficheiro se não existir."""
    db_path.parent.mkdir(parents= True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def criar_schema(conn: sqlite3.Connection) -> None:
    """Cria todas as tabelas e indices. Idempotente"""

    conn.executescript("""
        -- 1. metadados de uploads
CREATE TABLE IF NOT EXISTS _raw_snapshots (
    snapshot_data    DATE      NOT NULL,
    tabela           TEXT      NOT NULL CHECK (tabela IN ('pagamentos','presencas')),
    ficheiro_origem  TEXT      NOT NULL,
    hash_ficheiro    TEXT      NOT NULL,
    n_linhas         INTEGER   NOT NULL,
    cobertura_de     DATE,
    cobertura_ate    DATE,
    gaps_conhecidos  TEXT,
    ingerido_em      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (snapshot_data, tabela)
);

-- 2. pagamentos (event-log com UPSERT por no_parcela; ADR 0002)
CREATE TABLE IF NOT EXISTS _raw_pagamentos (
    no_parcela              INTEGER PRIMARY KEY,
    pag_no_pag              INTEGER,
    pag_data                DATE,
    pag_anulado             TEXT    CHECK (pag_anulado IN ('Sim','Não')),
    pag_data_anulacao       TIMESTAMP,
    parcelas_disponivel     DATE,
    parcelas_descricao      TEXT,
    parcelas_valor_liquido  REAL,
    parcelas_promocoes      TEXT,
    inv_familia             TEXT,
    inv_descricao           TEXT,
    utente_no_insc          INTEGER,
    utente_status           TEXT,
    utente_data_insc        DATE,
    doc_nome                TEXT,
    utente_gestor           TEXT,
    utente_tipo_socio       TEXT,
    pag_meio_pagamento      TEXT,
    atualizado_em_snapshot  DATE    NOT NULL
);

-- 3. presenças (event-log com INSERT OR IGNORE; ADR 0002)
-- Colunas alinhadas com o export real do software de gestão (load_acessos):
-- entrada sem saída → sem permanência calculável. dia da semana é
-- derivável de `data`, por isso não se guarda.
CREATE TABLE IF NOT EXISTS _raw_presencas (
    utente_no_insc           INTEGER NOT NULL,
    data                     DATE    NOT NULL,
    hora_entrada             TEXT    NOT NULL,
    utente_nome              TEXT,
    turma_nome               TEXT,
    utente_perfil            TEXT,
    utente_estado_no_evento  TEXT,
    ingerido_em_snapshot     DATE    NOT NULL,
    PRIMARY KEY (utente_no_insc, data, hora_entrada)
);

-- 4. auditoria de mutações em pagamentos
CREATE TABLE IF NOT EXISTS _log_alteracoes (
    id             INTEGER   PRIMARY KEY AUTOINCREMENT,
    no_parcela     INTEGER   NOT NULL,
    snapshot_data  DATE      NOT NULL,
    campo          TEXT      NOT NULL,
    valor_antigo   TEXT,
    valor_novo     TEXT,
    detectado_em   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- índices
CREATE INDEX IF NOT EXISTS ix_pagamentos_socia_mes
    ON _raw_pagamentos (utente_no_insc, parcelas_disponivel);
CREATE INDEX IF NOT EXISTS ix_pagamentos_mes
    ON _raw_pagamentos (parcelas_disponivel);
CREATE INDEX IF NOT EXISTS ix_presencas_socia_data
    ON _raw_presencas (utente_no_insc, data DESC);
CREATE INDEX IF NOT EXISTS ix_log_no_parcela
    ON _log_alteracoes (no_parcela);
""")


if __name__ == "__main__":
    conn = conectar()
    criar_schema(conn)
    tabelas = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    indices = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'ix_%' ORDER BY name"
    ).fetchall()
    print("Tabelas:", [t[0] for t in tabelas])
    print("Índices:", [i[0] for i in indices])
    conn.close()
