
import uuid
from fastapi import HTTPException
from pydantic import BaseModel
from api.app import getApp
from core import config

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