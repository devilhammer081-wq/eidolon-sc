"""Outings over HTTP (GLOSSARY.md「外出」): `POST /api/outings/solo` is the producer setting
out on his own — at the location the request names (`location_id`, null for one drawn) —
and answers with the walk as it stands: the outing with its notes, and the meeting it ended
in, with the conversation her opening stands in and that opening itself, null if he met no
one. The walk is asked of the model and kept whole before it answers; one that fails is 502,
a location the catalog has not 404. `GET /api/outings` lists the user's outings, the latest
first, with the lines of each and who, if anyone, he met."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from eidolon.assembly import Backend
from eidolon.characters import Character
from eidolon.outing_catalog import OutingLocation
from eidolon.outings import Message, Outing
from eidolon.sessions import UserId
from eidolon.solo_outings import NoLocation, OutingFailed


class SoloRequest(BaseModel):
    """Where the producer sets out, as he chose it; None for anywhere."""

    location_id: str | None = None


def add_outing_routes(app: FastAPI, backend: Backend) -> None:
    @app.exception_handler(NoLocation)
    async def no_location(_: Request, e: NoLocation) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=404)

    @app.exception_handler(OutingFailed)
    async def outing_failed(_: Request, e: OutingFailed) -> JSONResponse:
        """The walk could not be written; nothing was kept, so he may set out again at
        once."""
        return JSONResponse({"detail": str(e)}, status_code=502)

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
        "participants": list(outing.participants),
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
        "messages": [
            {
                "speaker": line.speaker,
                "kind": line.kind,
                "text": line.text,
                "event": line.event,
                "created_at": line.created_at.isoformat(),
            }
            for line in lines
        ],
    }
