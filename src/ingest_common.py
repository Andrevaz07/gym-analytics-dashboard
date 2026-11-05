"""
Helpers de ingestão partilhados por pagamentos e presenças.

A guarda de idempotência (hash do ficheiro + registo em _raw_snapshots)
é igual para qualquer fonte; só muda a `tabela`.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date
import sqlite3
import hashlib


def hash_ficheiro(path: Path) -> str:
    """SHA-256 do ficheiro, lido em chunks de 64 KB."""
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def snapshot_existente(
    conn: sqlite3.Connection,
    snapshot_data: date,
    tabela: str,
) -> str | None:
    """
    Devolve o hash guardado em _raw_snapshots para (snapshot_data, tabela),
    ou None se ainda não foi ingerido.
    """
    resultado = conn.execute(
        "SELECT hash_ficheiro FROM _raw_snapshots WHERE snapshot_data = ? AND tabela = ?",
        (snapshot_data.isoformat(), tabela),
    ).fetchone()

    if resultado is None:
        return None
    return resultado[0]
