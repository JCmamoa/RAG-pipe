"""Chat RAG via WebSocket com streaming.

Protocolo (JSON em texto):
  cliente -> {"type":"auth","token":"<jwt>"}                       (obrigatório como 1ª mensagem; reenvie para renovar)
  cliente -> {"type":"question","text":"...","document_ids":[...]}   (document_ids opcional)
  servidor-> {"type":"ready"} | {"type":"sources","sources":[...]} | {"type":"token","text":"..."}
             {"type":"done"} | {"type":"error","code":"...","message":"..."}
O token vai na primeira mensagem (não na URL) para não aparecer em logs de proxy/acesso.
"""
import asyncio
import json
import logging
import time
import uuid
from contextlib import aclosing

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import llm
from ..config import settings
from ..db import SessionLocal, org_session
from ..deps import AuthError, authenticate_token
from ..metrics import CHAT_QUESTIONS, LLM_FIRST_TOKEN, RETRIEVAL_LATENCY
from ..models import User
from ..prompts import NOT_FOUND_ANSWER, build_messages
from ..rate_limit import hit
from ..retrieval import retrieve

router = APIRouter()
log = logging.getLogger(__name__)

WS_UNAUTHORIZED = 4401
WS_FORBIDDEN = 4403


async def _auth(token) -> tuple[User, int]:
    async with SessionLocal() as session:
        user, payload = await authenticate_token(token, session)
    return user, int(payload["exp"])


async def _error(ws: WebSocket, code: str, message: str, **extra):
    await ws.send_json({"type": "error", "code": code, "message": message, **extra})


@router.websocket("/ws/chat")
async def chat(ws: WebSocket):
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), settings.ws_auth_timeout_seconds))
        if not isinstance(first, dict) or first.get("type") != "auth":
            raise AuthError("a primeira mensagem deve ser auth")
        token = first.get("token", "")
        user, exp = await _auth(token)
    except (asyncio.TimeoutError, json.JSONDecodeError, AuthError):
        await ws.close(code=WS_UNAUTHORIZED)
        return
    except WebSocketDisconnect:
        return
    await ws.send_json({"type": "ready"})

    history: list[dict] = []
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
                if not isinstance(msg, dict):
                    raise ValueError
            except ValueError:
                await _error(ws, "invalid_message", "Envie um objeto JSON")
                continue

            kind = msg.get("type")
            if kind == "auth":  # renovação do token sem derrubar a conexão
                try:
                    new_user, new_exp = await _auth(msg.get("token", ""))
                except AuthError:
                    await ws.close(code=WS_UNAUTHORIZED)
                    return
                if new_user.id != user.id:
                    await ws.close(code=WS_FORBIDDEN)
                    return
                token, user, exp = msg["token"], new_user, new_exp
                await ws.send_json({"type": "ready"})
                continue
            if kind != "question":
                await _error(ws, "invalid_message", "Tipo de mensagem desconhecido")
                continue

            # Revalida a cada pergunta: expiração do JWT e usuário desativado/alterado.
            if time.time() >= exp:
                await _error(ws, "token_expired", "Token expirado: envie uma nova mensagem auth")
                continue
            try:
                user, exp = await _auth(token)
            except AuthError:
                await ws.close(code=WS_UNAUTHORIZED)
                return

            retry = await hit("chat", str(user.id), settings.rl_chat_per_min)
            if retry:
                CHAT_QUESTIONS.labels("rate_limited").inc()
                await _error(ws, "rate_limited", "Muitas perguntas por minuto", retry_after=retry)
                continue

            text = msg.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > settings.max_question_chars:
                await _error(ws, "invalid_question", f"Pergunta vazia ou acima de {settings.max_question_chars} caracteres")
                continue
            try:
                doc_ids = [uuid.UUID(str(d)) for d in (msg.get("document_ids") or [])][:50]
            except ValueError:
                await _error(ws, "invalid_question", "document_ids inválidos")
                continue

            await _answer(ws, user, text.strip(), doc_ids or None, history)
    except (WebSocketDisconnect, RuntimeError):
        return  # cliente saiu (ou o socket já estava fechado)


async def _answer(ws: WebSocket, user: User, question: str, doc_ids, history: list[dict]):
    t0 = time.perf_counter()
    try:
        qvec = (await llm.embed([question], is_query=True))[0]
        # A transação de busca fecha ANTES do streaming: nada de conexão presa durante o LLM.
        async with org_session(user.org_id) as session:
            hits = await retrieve(session, user.org_id, qvec, settings.retrieval_top_k, doc_ids)
    except llm.LLMError:
        log.exception("falha na recuperação", extra={"user_id": str(user.id)})
        CHAT_QUESTIONS.labels("upstream_error").inc()
        await _error(ws, "upstream", "Não foi possível consultar os documentos agora")
        return
    RETRIEVAL_LATENCY.observe(time.perf_counter() - t0)

    await ws.send_json({"type": "sources", "sources": [
        {"n": n, "document_id": str(h.document_id), "filename": h.filename, "page": h.page,
         "score": round(h.score, 4), "snippet": h.content[:240]}
        for n, h in enumerate(hits, start=1)]})

    parts: list[str] = []
    if not hits:
        parts.append(NOT_FOUND_ANSWER)
        await ws.send_json({"type": "token", "text": NOT_FOUND_ANSWER})
    else:
        t1 = time.perf_counter()
        try:
            async with aclosing(llm.stream_chat(build_messages(question, hits, history))) as stream:
                async for piece in stream:
                    if not parts:
                        LLM_FIRST_TOKEN.observe(time.perf_counter() - t1)
                    parts.append(piece)
                    await ws.send_json({"type": "token", "text": piece})
        except llm.LLMError:
            log.exception("falha no LLM", extra={"user_id": str(user.id)})
            CHAT_QUESTIONS.labels("upstream_error").inc()
            await _error(ws, "upstream", "O modelo não respondeu. Tente novamente")
            return

    CHAT_QUESTIONS.labels("ok" if hits else "no_context").inc()
    await ws.send_json({"type": "done"})
    history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": "".join(parts)}])
    del history[:-2 * settings.chat_history_turns]
    log.info("pergunta respondida", extra={"user_id": str(user.id), "org_id": str(user.org_id),
                                           "sources": len(hits), "ms": int((time.perf_counter() - t0) * 1000)})
