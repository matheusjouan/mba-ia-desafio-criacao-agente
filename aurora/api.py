"""API HTTP do assistente do Residencial Aurora."""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException
from google.adk.sessions import Session
from pydantic import BaseModel

from . import db
from . import repositorio
from .runtime import (
    confirmacoes_pendentes,
    criar_sessao,
    executar,
    mensagem_texto,
    obter_sessao,
    texto_resposta,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Primeira subida sem restauração: carrega o estado inicial de dados/.
    if not repositorio.listar_areas():
        db.restaurar()
    yield


app = FastAPI(title="Residencial Aurora", lifespan=lifespan)


class CriarSessao(BaseModel):
    apartamento: str


class SessaoCriada(BaseModel):
    session_id: str


class Mensagem(BaseModel):
    texto: str


class ConfirmacaoPendente(BaseModel):
    id: str
    acao: str
    detalhes: dict


class RespostaAssistente(BaseModel):
    resposta: str
    confirmacoes_pendentes: list[ConfirmacaoPendente]


async def _sessao_ou_404(session_id: str) -> Session:
    sessao = await obter_sessao(session_id)
    if sessao is None:
        raise HTTPException(status_code=404, detail="Sessão não encontrada.")
    return sessao


# --- Sessões -----------------------------------------------------------------


@app.post("/sessoes", status_code=201, response_model=SessaoCriada)
async def post_sessao(body: CriarSessao) -> SessaoCriada:
    apartamento = body.apartamento.strip()
    if not repositorio.apartamento_existe(apartamento):
        raise HTTPException(status_code=422, detail="Apartamento inexistente.")
    sessao = await criar_sessao(apartamento)
    return SessaoCriada(session_id=sessao.id)


async def _responder(session_id: str, eventos) -> RespostaAssistente:
    sessao = await _sessao_ou_404(session_id)
    return RespostaAssistente(
        resposta=texto_resposta(eventos),
        confirmacoes_pendentes=confirmacoes_pendentes(sessao),
    )


@app.post("/sessoes/{session_id}/mensagens", response_model=RespostaAssistente)
async def post_mensagem(session_id: str, body: Mensagem) -> RespostaAssistente:
    await _sessao_ou_404(session_id)
    eventos = await executar(session_id, mensagem_texto(body.texto))
    return await _responder(session_id, eventos)


@app.get("/sessoes/{session_id}/eventos")
async def get_eventos(session_id: str) -> list[dict]:
    sessao = await _sessao_ou_404(session_id)
    return [ev.model_dump(mode="json", exclude_none=True) for ev in sessao.events]


# --- Rotas de verificação (leem o banco direto, sem passar pelo modelo) -------


@app.get("/apartamentos/{numero}/reservas")
async def get_reservas(numero: str) -> list[dict]:
    return repositorio.reservas_do_apartamento(numero)


@app.get("/apartamentos/{numero}/visitantes")
async def get_visitantes(numero: str) -> list[dict]:
    return repositorio.visitantes_do_apartamento(numero)


def main() -> None:
    uvicorn.run("aurora.api:app", host="127.0.0.1", port=8000)
