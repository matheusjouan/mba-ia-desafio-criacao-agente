"""Runtime do ADK: serviço de sessão persistido em SQLite."""

from google.adk.sessions import Session
from google.adk.sessions.sqlite_session_service import SqliteSessionService

from .config import APP_NAME, DB_SESSOES, VAR

# Todas as sessões ficam sob o mesmo user_id; quem identifica o morador é o
# apartamento gravado no state da sessão no momento da criação.
USER_ID = "morador"
CHAVE_APARTAMENTO = "apartamento"

VAR.mkdir(exist_ok=True)
session_service = SqliteSessionService(str(DB_SESSOES))


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
