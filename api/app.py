import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core import config

app = FastAPI()

def runApp():
    # Routes
    from api.routes import game
    from ws import wsManager

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Running the actual uvicorn server
    uvicorn.run(app, host=config.uvicorn_host, port=config.uvicorn_port)

def getApp():
    global app
    return app