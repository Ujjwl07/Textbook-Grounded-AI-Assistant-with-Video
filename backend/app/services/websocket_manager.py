import logging
from collections import defaultdict
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[job_id].add(websocket)
        logger.info(
            "WebSocket opened for job %s (%s listener(s))",
            job_id, len(self._connections[job_id]),
        )

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        sockets = self._connections.get(job_id)
        if not sockets:
            return
        sockets.discard(websocket)
        logger.info(
            "WebSocket closed for job %s (%s listener(s) left)", job_id, len(sockets)
        )
        if not sockets:
            self._connections.pop(job_id, None)

    async def broadcast(self, job_id: str, payload: dict) -> None:
        sockets = list(self._connections.get(job_id, set()))
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(job_id, websocket)


websocket_manager = WebSocketManager()
