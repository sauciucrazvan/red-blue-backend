from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from core import config

import os

connection = None
session = None
base = declarative_base()

def initConnection() -> None:
    global connection, base, session

    from models.game_model import Game
    from models.round_model import Round

    if config.debug:
        print("[DEBUG]: Initializing connection...")

    os.chdir(os.path.dirname(__file__))
    engine = create_engine("sqlite:///red-blue.sqlite",
        pool_size=10,
        max_overflow=20,
        pool_timeout=30,
        pool_recycle=120
    )

    connection = engine.connect()
    session = sessionmaker(bind=engine)
    base.metadata.create_all(engine)

    if config.debug:
        print("[DEBUG]: Initialized connection!")

def getConnection() -> Connection:
    global connection

    if connection is None:
        raise Exception("Connection not initialized. Call initConnection() first.")

    return connection

def getBase():
    global base

    if base is None:
        raise Exception("Base not initialized. Call initConnection() first.")

    return base

def getSession():
    global session

    if session is None:
        raise Exception("Session not initialized. Call initConnection() first.")
    
    return session()