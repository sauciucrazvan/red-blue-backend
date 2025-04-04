import uvicorn
from fastapi import FastAPI
from core import config

app = FastAPI()

def runApp():
    # Routes
    from api.routes import game

    # Running the actual uvicorn server
    uvicorn.run(app, host=config.uvicorn_host, port=config.uvicorn_port)

def getApp():
    global app
    return app