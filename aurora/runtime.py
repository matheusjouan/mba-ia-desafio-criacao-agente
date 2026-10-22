"""Runtime do ADK: sessões persistidas em SQLite, Runner e confirmações."""

import asyncio
from collections import defaultdict
from functools import cache

from google.adk.apps import App
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import Session
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from . import repositorio
from .config import APP_NAME, CHAVE_APARTAMENTO, DB_SESSOES, VAR

NOME_CONFIRMACAO = "adk_request_confirmation"

# Todas as sessões ficam sob o mesmo user_id; quem identifica o morador é o
# apartamento gravado no state da sessão no momento da criação.
USER_ID = "morador"

VAR.mkdir(exist_ok=True)
session_service = SqliteSessionService(str(DB_SESSOES))

# Uma execução por vez em cada sessão (sessões diferentes rodam em paralelo).
_travas: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


@cache
def _runner() -> Runner:
    # Import tardio: os agentes exigem chave de modelo, mas as rotas de
    # verificação e de sessão funcionam sem ela.
    from .agents.agent import root_agent

    return Runner(
        app=App(name=APP_NAME, root_agent=root_agent), session_service=session_service
    )


async def criar_sessao(apartamento: str) -> Session:
    return await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={CHAVE_APARTAMENTO: apartamento},
    )


async def obter_sessao(session_id: str) -> Session | None:
    return await session_service.get_session(
        app_name=APP_NAME, user_id=USER_ID, session_id=session_id
    )


async def _rodar(session_id: str, mensagem: types.Content) -> list[Event]:
    eventos = []
    async for evento in _runner().run_async(
        user_id=USER_ID, session_id=session_id, new_message=mensagem
    ):
        eventos.append(evento)
    return eventos


async def executar(session_id: str, mensagem: types.Content) -> list[Event]:
    """Roda o assistente com a mensagem e devolve os eventos gerados."""
    async with _travas[session_id]:
        return await _rodar(session_id, mensagem)


async def responder_confirmacao(
    session_id: str, confirmacao_id: str, confirmado: bool
) -> list[Event] | None:
    """Entrega ao ADK a resposta do morador a uma confirmação pendente.

    Devolve None (e não executa nada) se o id não estiver pendente nesta
    sessão: id inexistente, de outra sessão ou já respondido. A conferência e a
    execução ficam sob a mesma trava da sessão.
    """
    async with _travas[session_id]:
        sessao = await obter_sessao(session_id)
        pendentes = {p["id"] for p in confirmacoes_pendentes(sessao)} if sessao else set()
        if confirmacao_id not in pendentes:
            return None
        return await _rodar(
            session_id, mensagem_confirmacao(confirmacao_id, confirmado)
        )


def mensagem_texto(texto: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part(text=texto)])


def mensagem_confirmacao(confirmacao_id: str, confirmado: bool) -> types.Content:
    """Resposta do morador a um adk_request_confirmation pendente."""
    return types.Content(
        role="user",
        parts=[
            types.Part(
                function_response=types.FunctionResponse(
                    id=confirmacao_id,
                    name=NOME_CONFIRMACAO,
                    response={"confirmed": confirmado},
                )
            )
        ],
    )


def texto_resposta(eventos: list[Event]) -> str:
    """Junta o texto final dos agentes (sem raciocínio interno nem parciais)."""
    textos = []
    for evento in eventos:
        if evento.author == "user" or evento.partial or not evento.content:
            continue
        for parte in evento.content.parts or []:
            if parte.text and not parte.thought:
                textos.append(parte.text.strip())
    return "\n\n".join(t for t in textos if t)


def _partes(evento: Event) -> list[types.Part]:
    return list(evento.content.parts or []) if evento.content else []


def confirmacoes_pendentes(sessao: Session) -> list[dict]:
    """Pedidos de confirmação da sessão que ainda não receberam resposta.

    A fonte é o histórico de eventos gravado pelo ADK, não a conversa: uma
    confirmação só deixa de estar pendente quando existe um FunctionResponse
    adk_request_confirmation com o mesmo id, que só a rota de confirmações envia.
    """
    pedidos: dict[str, dict] = {}
    respondidos: set[str] = set()
    for evento in sessao.events:
        for parte in _partes(evento):
            chamada = parte.function_call
            if chamada and chamada.name == NOME_CONFIRMACAO and chamada.id:
                original = (chamada.args or {}).get("originalFunctionCall", {})
                pedidos[chamada.id] = _descrever(original)
            resposta = parte.function_response
            if resposta and resposta.name == NOME_CONFIRMACAO and resposta.id:
                respondidos.add(resposta.id)
    return [
        {"id": cid, **dados} for cid, dados in pedidos.items() if cid not in respondidos
    ]


def _descrever(chamada_original: dict) -> dict:
    acao = chamada_original.get("name", "")
    detalhes = dict(chamada_original.get("args") or {})
    if acao == "reservar_area" and "area" in detalhes:
        try:
            detalhes["taxa"] = repositorio.obter_area(detalhes["area"])["taxa"]
        except repositorio.DadoInvalido:
            pass
    return {"acao": acao, "detalhes": detalhes}
