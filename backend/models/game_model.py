import datetime
import uuid as uuid

from database import session as db

from sqlalchemy import Column, DateTime, Integer, String

Base = db.getBase()

class Game(Base):
    __tablename__ = 'game'
    id = Column(String, primary_key=True, nullable=False, default = lambda: str(uuid.uuid4()))
    code = Column(String, nullable=False)

    player1_name = Column(String, nullable=False)
    player2_name = Column(String, nullable=True)
    player1_score = Column(Integer, nullable=False)
    player2_score = Column(Integer, nullable=True)
    
    current_round = Column(Integer, nullable=False)
    game_state = Column(String, server_default="waiting", nullable=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    disconnected_at = Column(DateTime, nullable=True)
