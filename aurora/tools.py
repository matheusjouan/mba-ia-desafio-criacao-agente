"""Tools dos agentes.

Garantia 2: nenhuma tool recebe o apartamento como parâmetro. O apartamento é
lido de tool_context.state, gravado uma única vez na criação da sessão, e o
modelo não tem como alterá-lo.

Garantia 1: as tools que geram cobrança ou liberam acesso são registradas com
require_confirmation (o ADK pausa a execução até a rota de confirmações) e, como
segunda trava, só gravam se tool_context.tool_confirmation estiver aprovada.
"""

import json
from typing import Literal

from google.adk.tools import FunctionTool, ToolContext

from . import repositorio
from .config import CHAVE_APARTAMENTO, DADOS
from .repositorio import DadoInvalido

# Ids das áreas viram um enum no schema da tool, então o modelo só consegue
# passar um id válido (salao-de-festas, churrasqueira, quadra).
with open(DADOS / "areas.json", encoding="utf-8") as _f:
    _IDS_AREAS = tuple(a["id"] for a in json.load(_f))
AreaId = Literal[_IDS_AREAS]  # type: ignore[valid-type]


def _apartamento(tool_context: ToolContext) -> str:
    apartamento = tool_context.state.get(CHAVE_APARTAMENTO)
    if not apartamento:
        raise RuntimeError("Sessão sem apartamento definido.")
    return apartamento


def _confirmado(tool_context: ToolContext) -> bool:
    confirmacao = tool_context.tool_confirmation
    return bool(confirmacao and confirmacao.confirmed)


def _gera_cobranca(area_id: str) -> bool:
    return repositorio.obter_area(area_id)["taxa"] > 0


# --- Áreas e reservas -------------------------------------------------------


def listar_areas() -> dict:
    """Lista as áreas comuns que podem ser reservadas, com id, nome e taxa (R$).

    Taxa 0 significa que a reserva não gera cobrança.
    """
    return {"areas": repositorio.listar_areas()}


def verificar_disponibilidade(area: AreaId, data: str) -> dict:
    """Informa se uma área comum está livre ou ocupada numa data (AAAA-MM-DD).

    Não informa de quem é a reserva quando a data está ocupada.
    """
    try:
        data = repositorio.validar_data(data)
        repositorio.obter_area(area)
    except DadoInvalido as e:
        return {"erro": str(e)}
    ocupada = repositorio.data_ocupada(area, data)
    return {"area": area, "data": data, "situacao": "ocupada" if ocupada else "livre"}


def listar_minhas_reservas(tool_context: ToolContext) -> dict:
    """Lista as reservas ativas do apartamento do morador desta conversa."""
    apartamento = _apartamento(tool_context)
    return {"reservas": repositorio.reservas_do_apartamento(apartamento)}


def reservar_area(area: AreaId, data: str, tool_context: ToolContext) -> dict:
    """Reserva uma área comum para o apartamento do morador numa data (AAAA-MM-DD).

    Se a área tiver taxa, o sistema pede a aprovação do morador pelo aplicativo
    antes de gravar; basta chamar esta tool, sem pedir confirmação na conversa.
    """
    apartamento = _apartamento(tool_context)
    try:
        data = repositorio.validar_data(data)
        cobranca = _gera_cobranca(area)
    except DadoInvalido as e:
        return {"erro": str(e)}

    if cobranca and not _confirmado(tool_context):
        # Segunda trava da Garantia 1: sem aprovação registrada, nada é gravado.
        if repositorio.data_ocupada(area, data):
            return {"status": "indisponivel", "area": area, "data": data}
        return {"erro": "Esta reserva gera cobrança e precisa da aprovação do morador."}

    resultado = repositorio.criar_reserva(apartamento, area, data)
    if not resultado.criada:
        return {
            "status": "indisponivel",
            "area": area,
            "data": data,
            "mensagem": "A área já está reservada nesta data. Escolha outra data.",
        }
    resposta = {
        "status": "reservada",
        "codigo": resultado.codigo,
        "area": area,
        "data": data,
        "gera_cobranca": cobranca,
    }
    if cobranca:
        resposta["mensagem"] = "Aprovada pelo morador e gravada. Nada mais é necessário."
    return resposta


async def _reserva_requer_confirmacao(
    area: str, data: str, tool_context: ToolContext
) -> bool:
    """Pede confirmação só para área com taxa e data livre.

    Data ocupada não pede confirmação: a tool roda e recusa sem gravar nada.
    """
    try:
        data = repositorio.validar_data(data)
        return _gera_cobranca(area) and not repositorio.data_ocupada(area, data)
    except DadoInvalido:
        return False


def cancelar_minha_reserva(
    tool_context: ToolContext, codigo: str = "", area: str = "", data: str = ""
) -> dict:
    """Cancela uma reserva ativa do apartamento do morador.

    Informe o código da reserva, ou a área (id) e a data (AAAA-MM-DD).
    Só reservas do próprio apartamento podem ser canceladas.
    """
    apartamento = _apartamento(tool_context)
    try:
        canceladas = repositorio.cancelar_reservas(
            apartamento, codigo=codigo or None, area_id=area or None, data=data or None
        )
    except DadoInvalido as e:
        return {"erro": str(e)}
    if not canceladas:
        return {
            "status": "nao_encontrada",
            "mensagem": "Não há reserva ativa do seu apartamento com esses dados.",
        }
    return {"status": "cancelada", "reservas_canceladas": canceladas}


# --- Visitantes -------------------------------------------------------------


def listar_meus_visitantes(tool_context: ToolContext) -> dict:
    """Lista os visitantes autorizados do apartamento do morador desta conversa."""
    apartamento = _apartamento(tool_context)
    return {"visitantes": repositorio.visitantes_do_apartamento(apartamento)}


def autorizar_visitante(nome: str, data: str, tool_context: ToolContext) -> dict:
    """Autoriza a entrada de um visitante no prédio numa data (AAAA-MM-DD).

    Libera acesso, então o sistema sempre pede a aprovação do morador pelo
    aplicativo antes de gravar; basta chamar esta tool, sem pedir confirmação
    na conversa.
    """
    apartamento = _apartamento(tool_context)
    if not _confirmado(tool_context):
        # Segunda trava da Garantia 1: sem aprovação registrada, nada é gravado.
        return {"erro": "A autorização de visitante precisa da aprovação do morador."}
    try:
        visitante = repositorio.autorizar_visitante(apartamento, nome, data)
    except DadoInvalido as e:
        return {"erro": str(e)}
    return {
        "status": "autorizado",
        **visitante,
        "mensagem": "Aprovada pelo morador e gravada. Nada mais é necessário.",
    }


# --- Callback ---------------------------------------------------------------

_RESPOSTA_NEGADA_ADK = {"error": "This tool call is rejected."}


def traduzir_negacao(tool, args, tool_context, tool_response) -> dict | None:
    """after_tool_callback: deixa claro ao modelo que o morador negou a ação.

    A resposta padrão do ADK para uma confirmação negada parece um erro técnico,
    e o modelo tende a repetir a chamada (gerando outra confirmação). Aqui ela
    vira um resultado final e explícito.
    """
    if tool_response == _RESPOSTA_NEGADA_ADK:
        return {
            "status": "negada_pelo_morador",
            "mensagem": (
                "O morador negou esta ação no aplicativo e nada foi gravado. "
                "Não chame a tool de novo: só tente outra vez se o morador pedir "
                "explicitamente numa nova mensagem."
            ),
        }
    return None


# --- Registro das tools -----------------------------------------------------

TOOLS_RESERVAS = [
    FunctionTool(listar_areas),
    FunctionTool(verificar_disponibilidade),
    FunctionTool(listar_minhas_reservas),
    FunctionTool(reservar_area, require_confirmation=_reserva_requer_confirmacao),
    FunctionTool(cancelar_minha_reserva),
]

TOOLS_VISITANTES = [
    FunctionTool(listar_meus_visitantes),
    FunctionTool(autorizar_visitante, require_confirmation=True),
]
