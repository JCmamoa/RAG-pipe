"""WebSocket: autenticação, isolamento, streaming e revalidação do token (TestClient síncrono)."""
import time
import uuid

import jwt
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import settings
from app.main import app

from .helpers import seed_document


@pytest.fixture
def tc():
    with TestClient(app) as c:
        yield c


def _register(tc, org):
    email = f"{uuid.uuid4().hex[:10]}@{org}.test"
    token = tc.post("/auth/register", json={"org_name": org, "email": email,
                                            "password": "senha-forte-123"}).json()["access_token"]
    me = tc.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    return token, me


def _ask(ws, text, **extra):
    ws.send_json({"type": "question", "text": text, **extra})
    events = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] in ("done", "error"):
            return events


def test_streaming_with_sources_only_from_own_org(tc, fake_llm):
    token_a, a = _register(tc, "OrgA")
    token_b, b = _register(tc, "OrgB")
    tc.portal.call(seed_document, uuid.UUID(a["org_id"]), uuid.UUID(a["id"]), "segredo-a.pdf",
                   ["o cofre da organização A fica no subsolo"])
    tc.portal.call(seed_document, uuid.UUID(b["org_id"]), uuid.UUID(b["id"]), "publico-b.pdf",
                   ["o cofre da organização B fica no térreo"])

    with tc.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": token_b})
        assert ws.receive_json() == {"type": "ready"}
        events = _ask(ws, "onde fica o cofre?")

    sources = next(e for e in events if e["type"] == "sources")["sources"]
    assert [s["filename"] for s in sources] == ["publico-b.pdf"]
    assert "".join(e["text"] for e in events if e["type"] == "token") == "Resposta baseada no contexto [1]."
    assert events[-1] == {"type": "done"}
    prompt = fake_llm[-1][-1]["content"]
    assert "térreo" in prompt and "subsolo" not in prompt  # o contexto do LLM nunca contém dados da org A


def test_no_documents_answers_without_calling_llm(tc, fake_llm):
    token, _ = _register(tc, "Vazia")
    with tc.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": token})
        ws.receive_json()
        events = _ask(ws, "qualquer coisa?")
    assert events[-1] == {"type": "done"} and fake_llm == []


def test_bad_first_message_or_token_is_rejected(tc):
    with tc.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "question", "text": "oi"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401
    with tc.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": "lixo"})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4401


def test_expired_token_blocks_questions_until_reauth(tc):
    token, me = _register(tc, "OrgExp")
    short = jwt.encode({"sub": me["id"], "org_id": me["org_id"], "role": "admin", "exp": int(time.time()) + 2},
                       settings.jwt_secret, algorithm=settings.jwt_algorithm)
    with tc.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": short})
        assert ws.receive_json()["type"] == "ready"
        time.sleep(2.5)
        err = _ask(ws, "ainda posso perguntar?")[-1]
        assert err["type"] == "error" and err["code"] == "token_expired"
        ws.send_json({"type": "auth", "token": token})  # renova sem reconectar
        assert ws.receive_json()["type"] == "ready"
        assert _ask(ws, "e agora?")[-1] == {"type": "done"}


def test_cannot_swap_to_another_users_token(tc):
    token_a, _ = _register(tc, "OrgA")
    token_b, _ = _register(tc, "OrgB")
    with tc.websocket_connect("/ws/chat") as ws:
        ws.send_json({"type": "auth", "token": token_a})
        ws.receive_json()
        ws.send_json({"type": "auth", "token": token_b})
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4403
