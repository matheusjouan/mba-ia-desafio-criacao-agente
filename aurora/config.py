"""Caminhos e configurações do projeto."""

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env")

DADOS = RAIZ / "dados"
VAR = RAIZ / "var"
DB_CONDOMINIO = VAR / "condominio.db"
DB_SESSOES = VAR / "sessoes.db"

APP_NAME = "residencial_aurora"
MODELO = os.getenv("AURORA_MODELO") or "gemini-2.5-flash"
