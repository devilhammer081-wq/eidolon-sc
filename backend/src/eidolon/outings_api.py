"""Outings over HTTP (GLOSSARY.md「外出」): `POST /api/outings/solo` is the producer setting
out on his own — at the location the request names (`location_id`, null for one drawn) —
and answers with the walk as it stands: the outing with its notes, and the meeting it ended
in, with the conversation her opening stands in and that opening itself, null if he met no
one. The walk is asked of the model and kept whole before it answers; one that fails is 502,
a location the catalog has not 404. `POST /api/outings` sets out with company — one to
three characters (`character_ids`) at a location — the same way: its opening written and
kept whole before it answers. `GET /api/outings` lists the user's outings, the latest
first, with the lines of each and who, if anyone, he met.

An outing with company goes on over its own routes. `POST /api/outings/{id}/turns` says
something as the producer (支持 @某位同行角色，只她回应): the server-sent events of the turn —
what he said, who replies and her words as she speaks them, and the lines kept — streamed
as the conversation turns stream theirs; a turn that fails keeps nothing, its `error` told.
`POST /api/outings/{id}/events` sets off one of the location's events, answering with the
event and the lines it left once written. `POST /api/outings/{id}/end` ends it: each of
them settled with, the memory of it kept, and the outing over, answered with what it came
to. Writing to an outing not theirs, never there or over is 404 or 409; what the model
could not write is 502, the outing left as it stood."""

import json
from collections.abc import AsyncIterator
from dataclasses import asdict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from eidolon.assembly import Backend
from eidolon.characters import Character
from eidolon.group_outings import (
    BadCompany,
    NoCharacter,
    NoEvent,
    OutingFailed,
    SettledEach,
    TurnDone,
    TurnEvent,
)
from eidolon.outing_catalog import OutingLocation
from eidolon.outings import Message, Outing, OutingGone
from eidolon.sessions import UserId
from eidolon.solo_outings import NoLocation
from eidolon.solo_outings import OutingFailed as WalkFailed


class SoloRequest(BaseModel):
    """Where the producer sets out, as he chose it; None for anywhere."""

    location_id: str | None = None


class StartRequest(BaseModel):
    """Who comes along and where, as the producer chose it."""

    character_ids: list[str] = Field(min_length=1, max_length=3)
    location_id: str


class TurnRequest(BaseModel):
    """What the producer says or does; an @ names who replies."""

    text: str


class EventRequest(BaseModel):
    """Which of the location's events is set off."""

    event_id: str


def add_outing_routes(app: FastAPI, backend: Backend) -> None:
    @app.exception_handler(NoLocation)
    async def no_location(_: Request, e: NoLocation) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(NoCharacter)
    async def no_character(_: Request, e: NoCharacter) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(NoEvent)
    async def no_event(_: Request, e: NoEvent) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(BadCompany)
    async def bad_company(_: Request, e: BadCompany) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=422)

    @app.exception_handler(WalkFailed)
    async def walk_failed(_: Request, e: WalkFailed) -> JSONResponse:
        """The walk could not be written; nothing was kept, so he may set out again at
        once."""
        return JSONResponse({"detail": str(e)}, status_code=502)

    @app.exception_handler(OutingFailed)
    async def outing_failed(_: Request, e: OutingFailed) -> JSONResponse:
        """What the model was asked for could not be written; nothing was kept, so the
        producer may try again at once."""
        return JSONResponse({"detail": str(e)}, status_code=502)

    @app.exception_handler(OutingGone)
    async def outing_gone(_: Request, e: OutingGone) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=409)

    @app.post("/api/outings/solo", status_code=201)
    async def set_out(body: SoloRequest, user_id: UserId) -> dict:
        """The producer's walk on his own, written and kept whole: the outing with its
        notes, and the meeting, if any, he came home with."""
        walked = await backend.solo_outings.walk(user_id, body.location_id)
        return {
            "outing": _shown(
                walked.outing, await backend.outings.messages(user_id, walked.outing.id),
                walked.location, backend,
            ),
            "encounter": (
                {
                    "character_id": walked.met.character.id,
                    "conversation_id": walked.met.conversation.id,
                    "opening": walked.met.opening.shown(),
                }
                if walked.met else None
            ),
        }

    @app.post("/api/outings", status_code=201)
    async def set_out_with(body: StartRequest, user_id: UserId) -> dict:
        """The producer's outing with company, opened and kept whole: the outing with the
        lines of its opening, under way."""
        started = await backend.group_outings.open(
            user_id, body.character_ids, body.location_id
        )
        return {
            "outing": _shown(started.outing, started.lines, started.location, backend)
        }

    @app.get("/api/outings")
    async def list_outings(user_id: UserId) -> dict:
        """The user's outings, the latest first, each with its lines and who, if anyone, he
        met on it."""
        listed = []
        for outing in await backend.outings.listed(user_id):
            listed.append(_shown(
                outing, await backend.outings.messages(user_id, outing.id),
                backend.outing_catalog.get(outing.location_id), backend,
            ))
        return {"outings": listed}

    @app.post("/api/outings/{outing_id}/turns")
    async def outing_turn(
        outing_id: int, body: TurnRequest, user_id: UserId
    ) -> StreamingResponse:
        """One turn of the producer's outing, its events streamed: what he said (`user`),
        who replies (`speaker`) and her words as she speaks them (`delta`s), then the lines
        kept (`done`), or why it failed (`error`), nothing kept."""
        await _standing(backend, user_id, outing_id)

        async def events() -> AsyncIterator[str]:
            async for event in backend.group_outings.turn(user_id, outing_id, body.text):
                yield _sse(shown(event))

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/outings/{outing_id}/events")
    async def set_off(outing_id: int, body: EventRequest, user_id: UserId) -> dict:
        """One of the location's events, set off in the producer's outing: the event, and
        the lines it left, kept whole."""
        await _standing(backend, user_id, outing_id)
        happened = await backend.group_outings.happen(user_id, outing_id, body.event_id)
        return {
            "event": {"id": happened.event.id, "trigger": happened.event.trigger},
            "messages": [_line(line) for line in happened.lines],
        }

    @app.post("/api/outings/{outing_id}/end")
    async def end_outing(outing_id: int, user_id: UserId) -> dict:
        """The producer's outing over: what it came to for each of them — how her affinity
        changed and where it stands, and the memory kept of it — and the outing with its
        lines as they stand."""
        await _standing(backend, user_id, outing_id)
        ended = await backend.group_outings.end(user_id, outing_id)
        return {
            "outing": _shown(ended.outing, ended.lines, ended.location, backend),
            "settlement": [_settled(each) for each in ended.settled],
        }


async def _standing(backend: Backend, user_id: str, outing_id: int) -> Outing:
    """The user's outing, that the route may answer 404 for one never there and 409 for
    one over before anything of it runs."""
    outing = await backend.outings.outing(user_id, outing_id)
    if outing is None:
        raise HTTPException(404, "没有这次外出")
    if outing.status == "ended":
        raise HTTPException(409, "这次外出已经结束了")
    return outing


def shown(event: TurnEvent) -> dict:
    """The event as it goes out to the browser: `done`'s lines as the browser reads
    them."""
    if isinstance(event, TurnDone):
        return asdict(event) | {"messages": [_line(line) for line in event.messages]}
    return asdict(event)


def _settled(each: SettledEach) -> dict:
    """What ending the outing came to for one of them, as the browser reads it."""
    return {
        "character_id": each.character.id,
        "character_name": each.character.name,
        "change": (
            {
                "up": each.change.up,
                "tier": each.change.tier,
                "tier_changed": each.change.tier_changed,
                "cooldown": each.change.cooldown,
            }
            if each.change else None
        ),
        "affinity": each.status.shown(),
        "memory": each.memory.text if each.memory else None,
    }


def _line(line: Message) -> dict:
    """A line of an outing as the browser reads it."""
    return {
        "speaker": line.speaker,
        "kind": line.kind,
        "text": line.text,
        "event": line.event,
        "created_at": line.created_at.isoformat(),
    }


def _participants(outing: Outing, backend: Backend) -> list[dict]:
    """Who came along, as the browser reads them: their names should the configuration
    still have them, null for one it no longer does."""
    shown = []
    for id in outing.participants:
        character: Character | None = backend.characters.get(id)
        shown.append({
            "character_id": id,
            "character_name": character.name if character else None,
            "color": character.color if character else None,
        })
    return shown


def _shown(
    outing: Outing, lines: list[Message], location: OutingLocation | None, backend: Backend
) -> dict:
    """The outing as the browser reads it, with its lines and who, if anyone, was met: the
    speaker of its ending line, with her name should the configuration still have her.
    `location` is where it was in the catalog; its identifier stands in for its name should
    the catalog no longer have it."""
    encounter = next(
        (line.speaker for line in lines if line.kind == "ending" and line.speaker), None
    )
    character: Character | None = backend.characters.get(encounter) if encounter else None
    return {
        "id": outing.id,
        "kind": outing.kind,
        "location_id": outing.location_id,
        "location_name": location.name if location else outing.location_id,
        "participants": _participants(outing, backend),
        "status": outing.status,
        "created_at": outing.created_at.isoformat(),
        "ended_at": outing.ended_at.isoformat() if outing.ended_at else None,
        "encounter": (
            {
                "character_id": encounter,
                "character_name": character.name if character else None,
            }
            if encounter else None
        ),
        "messages": [_line(line) for line in lines],
    }


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
