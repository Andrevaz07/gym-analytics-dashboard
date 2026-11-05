"""
Testes da ingestão por pasta (`src.entrada`).

A gerente larga o ficheiro em data/entrada/ e nunca mais lhe toca. Não
há ninguém para ler um traceback nem para corrigir um nome de ficheiro,
por isso o que se testa aqui é sobretudo o que acontece quando corre
mal: o relatório errado, o ficheiro repetido, a cópia a meio.
"""
import shutil
import sqlite3

import pandas as pd
import pytest

from src import entrada
from src.entrada import processar_entrada


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    """A pausa entre medições de tamanho não tem de existir nos testes."""
    monkeypatch.setattr(entrada, "SEGUNDOS_ENTRE_MEDICOES", 0)


@pytest.fixture(autouse=True)
def sem_nuvem_real(monkeypatch):
    """
    O .env de uma máquina pode apontar para a pasta do iCloud a sério.
    Nenhum teste pode lá escrever — quem quer nuvem, pede a fixture.
    """
    monkeypatch.delenv("GINASIO_COPIAS_NUVEM", raising=False)


@pytest.fixture
def nuvem(tmp_path, monkeypatch):
    """Uma pasta "sincronizada" falsa, configurada como no .env."""
    pasta = tmp_path / "iCloud" / "Ginasio-Copias"
    pasta.parent.mkdir()
    monkeypatch.setenv("GINASIO_COPIAS_NUVEM", str(pasta))
    return pasta


@pytest.fixture
def pastas(tmp_path):
    """A pasta onde se larga e a pasta para onde se arruma."""
    caixa = tmp_path / "entrada"
    caixa.mkdir()
    return caixa, tmp_path / "arquivo"


@pytest.fixture
def largar(pastas):
    """Fábrica: grava um df na pasta de entrada com o nome que se quiser."""
    caixa, _ = pastas

    def _largar(df: pd.DataFrame, nome: str):
        caminho = caixa / nome
        df.to_excel(caminho, index=False)
        return caminho

    return _largar


def _correr(db, pastas):
    caixa, arquivo = pastas
    return processar_entrada(db, pasta=caixa, arquivo=arquivo)


def _linhas(db, tabela):
    return db.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]


# ------------------------------------------------------------- caminho feliz


def test_pagamentos_entram_e_sao_arrumados(db, pastas, largar, df_base):
    """
    O nome com que o ficheiro chega não interessa nada: a data vem do
    conteúdo (o último `pag_data`, aqui 01-02-2026) e o ficheiro sai da
    caixa de entrada com o nome da convenção.
    """
    caixa, arquivo = pastas
    largar(df_base, "extração final (3).xlsx")

    (r,) = _correr(db, pastas)

    assert r.estado == "ingerido"
    assert r.tipo == "pagamentos"
    assert str(r.snapshot) == "2026-02-01"
    assert _linhas(db, "_raw_pagamentos") == 3

    assert (arquivo / "2026-02-01_pagamentos.xlsx").exists()
    assert entrada.ficheiros_pousados(caixa) == []


def test_acessos_sao_reconhecidos_pelas_colunas(db, pastas, largar, df_base_acessos):
    """
    O mesmo ficheiro de entrada pode ser qualquer um dos dois relatórios.
    Distingui-los pelas colunas evita pedir à gerente que diga qual é.
    """
    _, arquivo = pastas
    largar(df_base_acessos, "acessos.xlsx")

    (r,) = _correr(db, pastas)

    assert r.estado == "ingerido"
    assert r.tipo == "presencas"
    assert _linhas(db, "_raw_presencas") == 3
    assert (arquivo / "2026-01-07_acessos.xlsx").exists()


def test_pasta_vazia_nao_devolve_nada(db, pastas):
    assert _correr(db, pastas) == []


# ------------------------------------------------------------ o que corre mal


def test_relatorio_errado_e_recusado_com_a_razao(db, pastas, largar, df_base):
    """
    A 05-08-2026 o ginásio exportou o relatório de documentos de
    facturação em vez do de parcelas. Sem esta guarda, a ingestão
    automática engoliria dados errados sem ninguém dar por nada.
    """
    caixa, _ = pastas
    largar(df_base.drop(columns=["no_parcela", "inv_familia"]), "pagamentos.xlsx")

    (r,) = _correr(db, pastas)

    assert r.estado == "problema"
    assert "no_parcela" in r.mensagem
    assert _linhas(db, "_raw_pagamentos") == 0

    posto_de_lado = caixa / entrada.NOME_PROBLEMAS / "pagamentos.xlsx"
    assert posto_de_lado.exists()
    assert "no_parcela" in posto_de_lado.with_suffix(".xlsx.txt").read_text(
        encoding="utf-8"
    )


def test_ficheiro_recusado_sai_da_caixa_de_entrada(db, pastas, largar, df_base):
    """
    Se ficasse na caixa, voltava a falhar a cada arranque do painel e a
    mesma mensagem repetia-se para sempre.
    """
    caixa, _ = pastas
    largar(df_base.drop(columns=["no_parcela"]), "errado.xlsx")

    _correr(db, pastas)
    assert entrada.ficheiros_pousados(caixa) == []

    assert _correr(db, pastas) == []


def test_o_mesmo_ficheiro_duas_vezes_so_entra_uma(db, pastas, largar, df_base):
    """
    Arrastar duas vezes é o engano mais provável de todos. É reconhecido
    pelo hash, antes sequer de abrir o ficheiro.
    """
    caixa, arquivo = pastas
    largar(df_base, "pagamentos.xlsx")
    _correr(db, pastas)

    # o mesmo ficheiro outra vez, com outro nome — é o hash que o apanha
    arquivada = next(arquivo.glob("*.xlsx"))
    shutil.copy(arquivada, caixa / "outra vez.xlsx")

    (r,) = _correr(db, pastas)

    assert r.estado == "repetido"
    assert "já tinha entrado" in r.mensagem
    assert _linhas(db, "_raw_pagamentos") == 3


def test_mesmo_mes_com_conteudo_diferente_pede_decisao(db, pastas, largar, df_base):
    """
    Duas extrações do mesmo mês com dados diferentes podem ser uma
    correção — ou o ficheiro errado. Quem decide é uma pessoa, não isto.
    """
    largar(df_base, "primeira.xlsx")
    _correr(db, pastas)

    alterado = df_base.copy()
    alterado.loc[0, "parcelas_valor_liquido"] = 99.9
    largar(alterado, "segunda.xlsx")

    (r,) = _correr(db, pastas)

    assert r.estado == "problema"
    assert "hash diferente" in r.mensagem


def test_ficheiro_que_nao_e_excel(db, pastas):
    caixa, _ = pastas
    (caixa / "extracao.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    (r,) = _correr(db, pastas)

    assert r.estado == "problema"
    assert ".xlsx" in r.mensagem


def test_ficheiro_a_meio_da_copia_fica_para_a_proxima(db, pastas):
    """
    Um ficheiro grande aparece na pasta antes de estar todo lá. Zero
    bytes é o primeiro instante dessa cópia: adiar é melhor do que
    declarar o ficheiro corrompido.
    """
    caixa, _ = pastas
    (caixa / "a-copiar.xlsx").touch()

    (r,) = _correr(db, pastas)

    assert r.estado == "adiado"
    assert len(entrada.ficheiros_pousados(caixa)) == 1


# ------------------------------------------------- ordem das extrações


def _extracao_seguinte(df_base: pd.DataFrame) -> pd.DataFrame:
    """
    A mesma janela vista um mês depois: a sócia 100 cancelou (todas as
    linhas dela passam a dizer M) e a 200 pagou Março, o que empurra a
    cobertura de 01-02 para 05-03.
    """
    marco = df_base.iloc[[1]].assign(
        no_parcela=4,
        pag_no_pag=40,
        pag_data=pd.Timestamp("2026-03-05"),
        parcelas_disponivel=pd.Timestamp("2026-03-01"),
    )
    seguinte = pd.concat([df_base, marco], ignore_index=True)
    seguinte.loc[seguinte["utente_no_insc"] == 100, "utente_status"] = "M"
    return seguinte


def _estado_parcela(db, no_parcela):
    return db.execute(
        "SELECT utente_status FROM _raw_pagamentos WHERE no_parcela = ?",
        (no_parcela,),
    ).fetchone()[0]


def test_extracoes_juntas_entram_da_mais_antiga_para_a_mais_recente(
    db, pastas, largar, df_base
):
    """
    Os nomes são os que o browser dá a dois downloads seguidos. Por ordem
    alfabética o "(1)" — o mais recente — vinha primeiro, e o antigo
    entrava por cima a repor a sócia 100 como activa.
    """
    largar(df_base, "Historico Parcelas.xlsx")
    largar(_extracao_seguinte(df_base), "Historico Parcelas (1).xlsx")

    resultados = _correr(db, pastas)

    assert [r.estado for r in resultados] == ["ingerido", "ingerido"]
    assert [str(r.snapshot) for r in resultados] == ["2026-02-01", "2026-03-05"]
    assert _estado_parcela(db, 1) == "M"


def test_extracao_de_pagamentos_mais_antiga_que_a_ultima_e_recusada(
    db, pastas, largar, df_base
):
    """
    A antiga a chegar depois, noutro dia, não pode passar por cima do que
    a recente já disse. Vai para os problemas e a base fica como estava.
    """
    caixa, _ = pastas
    largar(_extracao_seguinte(df_base), "recente.xlsx")
    _correr(db, pastas)

    largar(df_base, "antiga.xlsx")
    (r,) = _correr(db, pastas)

    assert r.estado == "problema"
    assert "05-03-2026" in r.mensagem
    assert _estado_parcela(db, 1) == "M"
    assert (caixa / entrada.NOME_PROBLEMAS / "antiga.xlsx").exists()


def test_acessos_mais_antigos_entram_na_mesma(db, pastas, largar, df_base_acessos):
    """
    Nas presenças a ordem não importa — o INSERT OR IGNORE nunca altera o
    que já existe — e uma extração antiga só pode acrescentar o que falta.
    """
    recente = df_base_acessos.assign(data=df_base_acessos["data"] + pd.Timedelta(days=30))
    largar(recente, "recente.xlsx")
    _correr(db, pastas)

    largar(df_base_acessos, "antiga.xlsx")
    (r,) = _correr(db, pastas)

    assert r.estado == "ingerido"
    assert _linhas(db, "_raw_presencas") == 6


def test_duas_copias_do_mesmo_ficheiro_na_mesma_leva(db, pastas, largar, df_base):
    """
    As duas passam a primeira fase, porque nessa altura nenhuma entrou
    ainda. A segunda tem de ser apanhada como repetida na segunda fase.
    """
    caixa, _ = pastas
    original = largar(df_base, "pagamentos.xlsx")
    shutil.copy(original, caixa / "pagamentos (1).xlsx")

    resultados = _correr(db, pastas)

    assert sorted(r.estado for r in resultados) == ["ingerido", "repetido"]
    assert _linhas(db, "_raw_pagamentos") == 3


# ----------------------------------------------------------- ruído e backup


def test_ficheiros_de_sistema_nao_sao_processados(db, pastas):
    """
    O `.DS_Store` do macOS, o temporário do Excel aberto e o próprio
    LEIA-ME que vive na pasta. Nenhum é uma extração.
    """
    caixa, _ = pastas
    for nome in (".DS_Store", "~$extracao.xlsx", "LEIA-ME.txt", "Thumbs.db"):
        (caixa / nome).write_text("x", encoding="utf-8")

    assert entrada.ficheiros_pousados(caixa) == []
    assert _correr(db, pastas) == []


def test_backup_antes_de_tocar_na_base(db, pastas, largar, df_base):
    """
    A ADR 0005 pede cópia antes de cada ingestão. Com a ingestão
    automática deixa de haver um humano a lembrar-se de a fazer.
    """
    largar(df_base, "pagamentos.xlsx")
    _correr(db, pastas)

    bd = entrada._ficheiro_da_ligacao(db)
    assert list(bd.parent.glob(f"{bd.name}.bak-*"))


def test_backup_guarda_o_estado_anterior(db, pastas, largar, df_base):
    """A cópia é de antes da ingestão — senão não servia para recuar."""
    largar(df_base, "pagamentos.xlsx")
    _correr(db, pastas)

    bd = entrada._ficheiro_da_ligacao(db)
    (copia,) = bd.parent.glob(f"{bd.name}.bak-*")

    with sqlite3.connect(copia) as antes:
        assert antes.execute("SELECT COUNT(*) FROM _raw_pagamentos").fetchone()[0] == 0


# --------------------------------------------------------------- nuvem


def test_copia_na_nuvem_e_do_estado_depois_da_ingestao(db, pastas, largar, df_base, nuvem):
    """
    A cópia local (de antes) serve para desfazer; a da nuvem serve para o
    disco morrer, e por isso tem de já ter a extração que acabou de entrar.
    """
    largar(df_base, "pagamentos.xlsx")
    _correr(db, pastas)

    (copia,) = nuvem.glob("base-*.sqlite")
    with sqlite3.connect(copia) as depois:
        assert depois.execute("SELECT COUNT(*) FROM _raw_pagamentos").fetchone()[0] == 3
    assert entrada.ultima_copia_na_nuvem() is not None


def test_sem_pasta_configurada_nao_ha_copia_nem_aviso(db, pastas, largar, df_base):
    largar(df_base, "pagamentos.xlsx")
    (r,) = _correr(db, pastas)

    assert r.estado == "ingerido"
    assert entrada.ultima_copia_na_nuvem() is None


def test_sem_ingestao_nao_ha_copia(db, pastas, nuvem):
    """Um ficheiro recusado não muda a base — não há nada novo a guardar."""
    caixa, _ = pastas
    (caixa / "extracao.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    _correr(db, pastas)

    assert not nuvem.exists() or not list(nuvem.glob("base-*.sqlite"))


def test_nuvem_indisponivel_avisa_mas_os_dados_entram(
    db, pastas, largar, df_base, tmp_path, monkeypatch
):
    """
    iCloud desligado: a pasta-mãe não existe. Criá-la à mão daria uma
    pasta que parece sincronizada e não é — por isso falha, e diz-se.
    """
    monkeypatch.setenv("GINASIO_COPIAS_NUVEM", str(tmp_path / "nao-existe" / "Ginasio"))
    largar(df_base, "pagamentos.xlsx")

    resultados = _correr(db, pastas)

    assert [r.estado for r in resultados] == ["ingerido", "aviso"]
    assert "só existem neste computador" in resultados[-1].mensagem
    assert _linhas(db, "_raw_pagamentos") == 3
    assert not (tmp_path / "nao-existe").exists()


def test_nuvem_guarda_seis_e_so_apaga_as_suas(db, nuvem):
    nuvem.mkdir()
    for dia in range(1, 9):
        (nuvem / f"base-2026-01-{dia:02d}.sqlite").write_text("x")
    (nuvem / "nota-da-gerente.txt").write_text("não mexer")

    entrada.copia_para_a_nuvem(db)

    guardadas = sorted(f.name for f in nuvem.glob("base-*.sqlite"))
    assert len(guardadas) == 6
    assert (nuvem / "nota-da-gerente.txt").exists()
    assert not list(nuvem.glob("*.parcial"))


def test_lancador_nao_processa_a_pasta_com_a_base_de_demonstracao(tmp_path):
    """
    Uma pasta copiada inteira de outra máquina pode levar um .env de
    demonstração. O lançador processava a pasta de entrada na mesma — a
    extração real entrava na base fictícia. Tem de recusar.
    """
    import os
    import subprocess
    import sys

    demo = tmp_path / "base_demo.sqlite"
    corrida = subprocess.run(
        [sys.executable, "-m", "src.entrada"],
        env={**os.environ, "GINASIO_DB": str(demo), "PYTHONIOENCODING": "utf-8"},
        capture_output=True, text=True, encoding="utf-8",
    )

    assert corrida.returncode == 0
    assert "demonstração" in corrida.stdout
    assert not demo.exists()
