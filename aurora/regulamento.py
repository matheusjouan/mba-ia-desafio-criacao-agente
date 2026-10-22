"""Acesso ao regulamento interno, um capítulo por vez.

Garantia 4: o regulamento nunca é carregado inteiro. O especialista recebe só o
índice de títulos e lê, sob demanda, o capítulo do assunto perguntado.
"""

import re
from dataclasses import dataclass
from functools import cache

from .config import DADOS

_CABECALHO = re.compile(r"^## (Capítulo ([IVXLC]+): .+)$", re.MULTILINE)
_ROMANOS = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


@dataclass(frozen=True)
class Capitulo:
    numero: int
    titulo: str
    texto: str


def _romano_para_int(romano: str) -> int:
    total = 0
    for atual, proximo in zip(romano, romano[1:] + " "):
        valor = _ROMANOS[atual]
        total += -valor if _ROMANOS.get(proximo, 0) > valor else valor
    return total


@cache
def capitulos() -> dict[int, Capitulo]:
    conteudo = (DADOS / "regulamento.md").read_text(encoding="utf-8")
    cabecalhos = list(_CABECALHO.finditer(conteudo))
    resultado = {}
    for i, m in enumerate(cabecalhos):
        fim = cabecalhos[i + 1].start() if i + 1 < len(cabecalhos) else len(conteudo)
        numero = _romano_para_int(m.group(2))
        resultado[numero] = Capitulo(numero, m.group(1), conteudo[m.start() : fim].strip())
    return resultado


def indice() -> str:
    """Só os títulos dos capítulos, um por linha (sem o conteúdo)."""
    return "\n".join(f"{c.numero}. {c.titulo}" for c in capitulos().values())
