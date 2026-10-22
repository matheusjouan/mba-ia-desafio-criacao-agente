"""Leitura e gravação dos dados do condomínio.

Toda função que lê ou altera reservas e visitantes recebe o apartamento e filtra
por ele no próprio SQL. Quem chama (as tools) passa sempre o apartamento da
sessão, nunca um valor vindo do modelo.
"""

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import date

from .db import conexao, transacao


class DadoInvalido(ValueError):
    """Entrada que não passa na validação (área inexistente, data mal formada...)."""


def validar_data(data: str) -> str:
    try:
        return date.fromisoformat(data.strip()).isoformat()
    except (ValueError, AttributeError):
        raise DadoInvalido(f"Data inválida: {data!r}. Use o formato AAAA-MM-DD.")


# --- Apartamentos e áreas ---------------------------------------------------


def apartamento_existe(numero: str) -> bool:
    with conexao() as conn:
        row = conn.execute(
            "SELECT 1 FROM apartamentos WHERE numero = ?", (numero,)
        ).fetchone()
    return row is not None


def listar_areas() -> list[dict]:
    with conexao() as conn:
        rows = conn.execute("SELECT id, nome, taxa FROM areas ORDER BY nome").fetchall()
    return [dict(r) for r in rows]


def obter_area(area_id: str) -> dict:
    with conexao() as conn:
        row = conn.execute(
            "SELECT id, nome, taxa FROM areas WHERE id = ?", (area_id,)
        ).fetchone()
    if row is None:
        ids = ", ".join(a["id"] for a in listar_areas())
        raise DadoInvalido(f"Área desconhecida: {area_id!r}. Áreas válidas: {ids}.")
    return dict(row)


# --- Reservas ---------------------------------------------------------------


def reservas_do_apartamento(apartamento: str) -> list[dict]:
    with conexao() as conn:
        rows = conn.execute(
            "SELECT codigo, area, data FROM reservas"
            " WHERE apartamento = ? AND status = 'ativa' ORDER BY data, area",
            (apartamento,),
        ).fetchall()
    return [dict(r) for r in rows]


def data_ocupada(area_id: str, data: str) -> bool:
    """Só diz se a data está ocupada, sem revelar de quem é a reserva."""
    with conexao() as conn:
        row = conn.execute(
            "SELECT 1 FROM reservas WHERE area = ? AND data = ? AND status = 'ativa'",
            (area_id, data),
        ).fetchone()
    return row is not None


@dataclass
class ResultadoReserva:
    criada: bool
    codigo: str | None = None


def _novo_codigo() -> str:
    return f"RSV-{secrets.token_hex(3).upper()}"


def criar_reserva(apartamento: str, area_id: str, data: str) -> ResultadoReserva:
    """Grava a reserva se a área estiver livre naquela data.

    Não há conferência prévia: a exclusividade é decidida pelo índice único
    parcial ux_reserva_ativa_area_data no momento do INSERT. Se outra reserva
    ativa já existe (inclusive uma gravada por outra requisição um instante
    antes), o INSERT falha e a reserva é recusada normalmente.
    """
    data = validar_data(data)
    obter_area(area_id)
    with conexao() as conn:
        for _ in range(20):
            codigo = _novo_codigo()
            try:
                with transacao(conn):
                    conn.execute(
                        "INSERT INTO codigos_emitidos (codigo) VALUES (?)", (codigo,)
                    )
                    conn.execute(
                        "INSERT INTO reservas (codigo, apartamento, area, data)"
                        " VALUES (?, ?, ?, ?)",
                        (codigo, apartamento, area_id, data),
                    )
                return ResultadoReserva(criada=True, codigo=codigo)
            except sqlite3.IntegrityError as e:
                if "codigos_emitidos" in str(e):
                    continue  # código já emitido algum dia: sorteia outro
                return ResultadoReserva(criada=False)
    raise RuntimeError("Não foi possível gerar um código de reserva inédito.")


def cancelar_reservas(
    apartamento: str,
    codigo: str | None = None,
    area_id: str | None = None,
    data: str | None = None,
) -> list[dict]:
    """Cancela reservas ativas DO APARTAMENTO que batem com os filtros.

    Reservas de outros apartamentos nunca são afetadas nem reveladas: o filtro
    por apartamento está no WHERE do UPDATE.
    """
    if not codigo and not (area_id and data):
        raise DadoInvalido("Informe o código da reserva ou a área e a data.")
    filtros = ["apartamento = ?", "status = 'ativa'"]
    params: list[str] = [apartamento]
    if codigo:
        filtros.append("codigo = ?")
        params.append(codigo.strip().upper())
    if area_id:
        filtros.append("area = ?")
        params.append(area_id)
    if data:
        filtros.append("data = ?")
        params.append(validar_data(data))
    where = " AND ".join(filtros)
    with conexao() as conn, transacao(conn):
        rows = conn.execute(
            f"SELECT codigo, area, data FROM reservas WHERE {where}", params
        ).fetchall()
        conn.execute(
            f"UPDATE reservas SET status = 'cancelada' WHERE {where}", params
        )
    return [dict(r) for r in rows]


# --- Visitantes ---------------------------------------------------------------


def visitantes_do_apartamento(apartamento: str) -> list[dict]:
    with conexao() as conn:
        rows = conn.execute(
            "SELECT nome, data FROM visitantes WHERE apartamento = ? ORDER BY data, id",
            (apartamento,),
        ).fetchall()
    return [dict(r) for r in rows]


def autorizar_visitante(apartamento: str, nome: str, data: str) -> dict:
    nome = " ".join(nome.split())
    if not nome:
        raise DadoInvalido("Informe o nome do visitante.")
    data = validar_data(data)
    with conexao() as conn, transacao(conn):
        conn.execute(
            "INSERT INTO visitantes (apartamento, nome, data) VALUES (?, ?, ?)",
            (apartamento, nome, data),
        )
    return {"nome": nome, "data": data}
