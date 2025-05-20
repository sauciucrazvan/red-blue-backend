from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict
import json

from api.app import getApp

app = getApp()

active_connections: Dict[str, set] = {}

async def notify_game_status(game_id: str, status_update: dict):
    if game_id in active_connections:
        for connection in active_connections[game_id]:
            await connection.send_text(json.dumps(status_update))

@app.websocket("/ws/game/{game_id}")
async def game_websocket(websocket: WebSocket, game_id: str):
    await websocket.accept()
    if game_id not in active_connections:
        active_connections[game_id] = set()
    active_connections[game_id].add(websocket)

    try:
        for connection in active_connections[game_id]:
            await connection.send_text(json.dumps({
                "message": "Your opponent has joined the game",
                "active_players": len(active_connections[game_id])
            }))

        while True:
            data = await websocket.receive_text()
            for connection in active_connections[game_id]:
                await connection.send_text(data)
    except WebSocketDisconnect:
        active_connections[game_id].remove(websocket)
        if not active_connections[game_id]:
            del active_connections[game_id]
