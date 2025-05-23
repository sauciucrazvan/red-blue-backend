
import uuid
from fastapi import HTTPException
from pydantic import BaseModel
from api.app import getApp
from core import config
from database import session as db
from datetime import datetime, timedelta, timezone

from models.game_model import Game

app = getApp()

class LoginRequest(BaseModel):
    password: str

@app.post("/api/v1/admin/login")
def login(request: LoginRequest):
    if request.password == config.admin_password:
        if not config.admin_token:
            config.admin_token = str(uuid.uuid4().hex)

        return {"message": "Successfully logged in!", "admin_token": config.admin_token}
    else:
        raise HTTPException(status_code=401, detail="Invalid password!")

class CleanupRequest(BaseModel):
    admin_token: str

@app.post("/api/v1/admin/cleanup")
def cleanup(request: CleanupRequest):
    if not config.admin_token:
        raise HTTPException(status_code=401, detail="Not logged in!")

    if request.admin_token != config.admin_token:
        raise HTTPException(status_code=401, detail="Invalid token!")

    session = db.getSession()
    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    games = session.query(Game).filter(Game.created_at < one_hour_ago).all()

    for game in games:
        try:
            session.delete(game)
            session.commit()
        except Exception as e:
            session.rollback()
            raise HTTPException(status_code=500, detail=f"Error deleting game: {str(e)}")

    return {"message": "Cleanup completed successfully!"}