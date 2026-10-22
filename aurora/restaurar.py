"""Comando de restauração: uv run aurora-restaurar [--sessoes]."""

import argparse

from . import db
from .config import DB_SESSOES


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restaura reservas e visitantes ao estado inicial de dados/."
    )
    parser.add_argument(
        "--sessoes",
        action="store_true",
        help="também apaga todas as sessões de conversa (var/sessoes.db)",
    )
    args = parser.parse_args()

    db.restaurar()
    print("Dados do condomínio restaurados a partir de dados/.")

    if args.sessoes:
        for sufixo in ("", "-wal", "-shm"):
            DB_SESSOES.with_name(DB_SESSOES.name + sufixo).unlink(missing_ok=True)
        print("Sessões apagadas.")


if __name__ == "__main__":
    main()
