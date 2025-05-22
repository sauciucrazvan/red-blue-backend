from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict
import json

from api.app import getApp

# from api.routes.game import DisconnectGame, disconnect_game

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
        while True:
            data = await websocket.receive_text()
            try:
                payload = json.loads(data)
                if payload.get("type") == "disconnect_event":
                    if payload.get("player_name") and payload.get("token"):
                        from api.routes.game import DisconnectGame, disconnect_game
                        disconnect_request = DisconnectGame(
                            game_id=game_id,
                            player_name=payload.get("player_name"),
                            token=payload.get("token")
                        )
                        await disconnect_game(disconnect_request)
            except Exception as e:
                print("Error parsing JSON:", e)

            for connection in active_connections[game_id]:
                await connection.send_text(data)
    except WebSocketDisconnect:
        active_connections[game_id].remove(websocket)
        if not active_connections[game_id]:
            del active_connections[game_id]
