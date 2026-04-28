import asyncio
import json
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from patent_agent.api.routers.analysis import _progress_store

router = APIRouter(prefix="/api/v1/analysis", tags=["stream"])


@router.get("/{analysis_id}/stream")
async def stream_progress(analysis_id: str):
    async def event_generator():
        sent = 0
        while True:
            events = _progress_store.get(analysis_id, [])
            for event in events[sent:]:
                yield {"data": json.dumps(event, ensure_ascii=False)}
                sent += 1
                if event.get("done"):
                    return
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
