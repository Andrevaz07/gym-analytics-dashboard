"""
Testes de `src.db` — que base de dados o painel aceita usar.

No Mac da gerente a base de demonstração nunca é a certa. Nas outras
máquinas é o normal, e tem de continuar a funcionar.
"""
from pathlib import Path

from src.db import demo_proibida

REAL = Path("data/ginasio.sqlite")
DEMO = Path("data/ginasio_demo.sqlite")


def test_no_mac_da_gerente_a_demo_e_recusada(monkeypatch):
    monkeypatch.setenv("GINASIO_PRODUCAO", "1")
    assert demo_proibida(DEMO)


def test_no_mac_da_gerente_a_base_real_passa(monkeypatch):
    monkeypatch.setenv("GINASIO_PRODUCAO", "1")
    assert not demo_proibida(REAL)


def test_fora_do_lancador_do_mac_a_demo_passa(monkeypatch):
    """O portátil e o repo público vivem da demo — não podem ser travados."""
    monkeypatch.delenv("GINASIO_PRODUCAO", raising=False)
    assert not demo_proibida(DEMO)
