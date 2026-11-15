"""The group chat over HTTP (GLOSSARY.md「群聊」): `GET /api/group` is the producer's chat —
its latest lines, each with who said them (a character's name and color, null for his own
words), the topic underway (null while none is), and whether anything was unread before
this reading of it, which it counts as. `GET /api/group/unseen` says the unread part
alone, for the chat's entry on the conversation list, without reading the chat.

`POST /api/group/turns` says something as the producer (支持 @某位角色，只她回应): the
server-sent events of the turn — what he said, who replies and her words as she speaks
them, and the lines kept — streamed as the conversation turns and the outing turns stream
theirs; a turn that fails keeps nothing, its `error` told. While the deployer has the
group chat closed, each of these is refused with 409."""

import json
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from eidolon.assembly import Backend
from eidolon.characters import Character
from eidolon.group_chat import (
    GroupChatOff,
    Message,
    Topic,
    TurnDone,
    TurnEvent,
)
from eidolon.sessions import UserId


class TurnRequest(BaseModel):
    """What the producer says; an @ names who replies."""

    text: str


def add_group_chat_routes(app: FastAPI, backend: Backend) -> None:
    @app.exception_handler(GroupChatOff)
    async def group_chat_off(_: Request, e: GroupChatOff) -> JSONResponse:
        return JSONResponse({"detail": "群聊没有开放"}, status_code=409)

    @app.get("/api/group")
    async def the_group(user_id: UserId) -> dict:
        """The producer's chat: its latest lines with who said them, the topic underway,
        and whether anything was unread — counted as read by this reading."""
        shown = await backend.group_chat.shown(user_id)
        return {
            "messages": [_line(line, backend) for line in shown.messages],
            "topic": _topic(shown.topic, backend),
            "unseen": shown.unread,
        }

    @app.get("/api/group/unseen")
    async def unseen(user_id: UserId) -> dict:
        """Whether a character has said anything in the chat since the producer last read
        it, without reading it now: for the chat's entry on the conversation list."""
        return {"unseen": await backend.group_chat.unread(user_id)}

    @app.post("/api/group/turns")
    async def group_turn(body: TurnRequest, user_id: UserId) -> StreamingResponse:
        """One turn of the producer in his chat, its events streamed: what he said
        (`user`), who replies (`speaker`) and her words as she speaks them (`delta`s), then
        the lines kept (`done`), or why it failed (`error`), nothing kept."""
        backend.group_chat.require_on()  # the closed chat's 409, before the stream

        async def events() -> AsyncIterator[str]:
            async for event in backend.group_chat.turn(user_id, body.text):
                yield _sse(shown(event, backend))

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )


def shown(event: TurnEvent, backend: Backend) -> dict:
    """The event as it goes out to the browser: `done`'s lines as the browser reads
    them."""
    if isinstance(event, TurnDone):
        return asdict(event) | {"messages": [_line(line, backend) for line in event.messages]}
    return asdict(event)


def _line(line: Message, backend: Backend) -> dict:
    """A line of the chat as the browser reads it, with who said it: her name and color
    should the configuration still have her, null for the producer's own words."""
    character: Character | None = backend.characters.get(line.speaker) if line.speaker else None
    return {
        "id": line.id,
        "speaker": line.speaker,
        "speaker_name": character.name if character else None,
        "color": character.color if character else None,
        "kind": line.kind,
        "text": line.text,
        "created_at": line.created_at.isoformat(),
    }


def _topic(topic: Topic | None, backend: Backend) -> dict | None:
    """The topic underway as the browser reads it, null while none is: who opened it,
    who has spoken in it and in what order, how many turns it has taken."""
    if topic is None:
        return None
    opener = backend.characters.get(topic.opener)
    return {
        "opener": topic.opener,
        "opener_name": opener.name if opener else None,
        "spoken": list(topic.spoken),
        "turns": topic.turns,
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
