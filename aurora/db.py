"""Banco SQLite com o estado do condomínio (áreas, reservas e visitantes).

Os arquivos de dados/ são só o estado inicial: são lidos na restauração e nunca
alterados. Tudo o que o assistente muda fica em var/condominio.db.
"""

import json
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import DADOS, DB_CONDOMINIO, VAR

SCHEMA = """
CREATE TABLE IF NOT EXISTS apartamentos (
    numero  TEXT PRIMARY KEY,
    morador TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS areas (
    id   TEXT PRIMARY KEY,
    nome TEXT NOT NULL,
    taxa REAL NOT NULL
);

-- Todo código já emitido, inclusive de reservas canceladas ou apagadas por uma
-- restauração. A PK garante que um código nunca é reutilizado.
CREATE TABLE IF NOT EXISTS codigos_emitidos (
    codigo TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS reservas (
    codigo      TEXT PRIMARY KEY REFERENCES codigos_emitidos(codigo),
    apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
    area        TEXT NOT NULL REFERENCES areas(id),
    data        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ativa' CHECK (status IN ('ativa', 'cancelada'))
);

-- Garantia 5: no máximo uma reserva ATIVA por área e data. O SQLite confere o
-- índice no próprio INSERT, então duas gravações simultâneas nunca passam juntas.
CREATE UNIQUE INDEX IF NOT EXISTS ux_reserva_ativa_area_data
    ON reservas (area, data) WHERE status = 'ativa';

CREATE TABLE IF NOT EXISTS visitantes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    apartamento TEXT NOT NULL REFERENCES apartamentos(numero),
    nome        TEXT NOT NULL,
    data        TEXT NOT NULL
);
"""


def _conectar() -> sqlite3.Connection:
    VAR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_CONDOMINIO, timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


_schema_criado = False


@contextmanager
def conexao() -> Iterator[sqlite3.Connection]:
    """Conexão em modo autocommit; transações são abertas explicitamente."""
    global _schema_criado
    conn = _conectar()
    try:
        if not _schema_criado:
            conn.executescript(SCHEMA)
            _schema_criado = True
        yield conn
    finally:
        conn.close()


@contextmanager
def transacao(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """BEGIN IMMEDIATE ... COMMIT, com ROLLBACK em caso de erro."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _ler_json(nome: str) -> list[dict]:
    with open(DADOS / nome, encoding="utf-8") as f:
        return json.load(f)


def restaurar() -> None:
    """Volta apartamentos, áreas, reservas e visitantes ao estado de dados/.

    A tabela codigos_emitidos não é limpa: códigos gerados antes da restauração
    continuam reservados e nunca serão emitidos de novo.
    """
    apartamentos = _ler_json("apartamentos.json")
    areas = _ler_json("areas.json")
    reservas = _ler_json("reservas.json")
    visitantes = _ler_json("visitantes.json")

    with conexao() as conn, transacao(conn):
        conn.execute("DELETE FROM visitantes")
        conn.execute("DELETE FROM reservas")
        conn.execute("DELETE FROM areas")
        conn.execute("DELETE FROM apartamentos")
        conn.executemany(
            "INSERT INTO apartamentos (numero, morador) VALUES (:numero, :morador)",
            apartamentos,
        )
        conn.executemany(
            "INSERT INTO areas (id, nome, taxa) VALUES (:id, :nome, :taxa)", areas
        )
        conn.executemany(
            "INSERT OR IGNORE INTO codigos_emitidos (codigo) VALUES (:codigo)",
            reservas,
        )
        conn.executemany(
            "INSERT INTO reservas (codigo, apartamento, area, data)"
            " VALUES (:codigo, :apartamento, :area, :data)",
            reservas,
        )
        conn.executemany(
            "INSERT INTO visitantes (apartamento, nome, data)"
            " VALUES (:apartamento, :nome, :data)",
            visitantes,
        )
