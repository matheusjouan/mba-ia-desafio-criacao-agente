"""Escolha do modelo usado pelos agentes.

Gemini (Google AI Studio) é o padrão. Se GOOGLE_API_KEY estiver vazia e
ANTHROPIC_API_KEY estiver preenchida, os agentes usam Claude pela API da Anthropic.
"""

import os

from google.adk.models.anthropic_llm import AnthropicLlm
from google.adk.models.base_llm import BaseLlm
from google.genai import types

from . import config  # noqa: F401  (carrega o .env antes de ler as variáveis)

MODELO_GEMINI_PADRAO = "gemini-2.5-flash"
MODELO_ANTHROPIC_PADRAO = "claude-haiku-5-5"


def criar_modelo() -> str | BaseLlm:
    if os.getenv("GOOGLE_API_KEY"):
        return os.getenv("AURORA_MODELO") or MODELO_GEMINI_PADRAO
    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicLlm(
            model=os.getenv("AURORA_MODELO_ANTHROPIC") or MODELO_ANTHROPIC_PADRAO
        )
    raise RuntimeError(
        "Nenhuma chave de modelo configurada: preencha GOOGLE_API_KEY "
        "(ou ANTHROPIC_API_KEY) no arquivo .env."
    )


def config_geracao() -> types.GenerateContentConfig | None:
    """Configuração de geração dos agentes.

    Com Claude, o raciocínio estendido fica desligado: o callback que lembra o
    pedido atual altera a requisição a cada turno, e a API da Anthropic recusa
    blocos de raciocínio reenviados com um histórico diferente do original.
    Para rotear e chamar tools, o raciocínio estendido não faz falta.
    """
    if isinstance(criar_modelo(), AnthropicLlm):
        return types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=0)
        )
    return None


def descrever_modelo() -> str:
    modelo = criar_modelo()
    return modelo if isinstance(modelo, str) else f"anthropic/{modelo.model}"
