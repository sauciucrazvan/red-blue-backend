import datetime
import uuid as uuid

from database import session as db

from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import relationship

Base = db.getBase()

class Game(Base):
    __tablename__ = 'game'
    id = Column(String, primary_key=True, nullable=False, default = lambda: str(uuid.uuid4()))
    code = Column(String, nullable=False)

    player1_name = Column(String, nullable=True)
    player2_name = Column(String, nullable=True)
    player1_score = Column(Integer, nullable=True)
    player2_score = Column(Integer, nullable=True)
    player1_token = Column(String, nullable=False, default = lambda: str(uuid.uuid4()))
    player2_token = Column(String, nullable=False, default = lambda: str(uuid.uuid4()))
    
    current_round = Column(Integer, nullable=False)
    current_round_id = Column(String, nullable=True)
    game_state = Column(String, server_default="waiting", nullable=False)

    created_at = Column(DateTime, default=datetime.datetime.now(datetime.timezone.utc), nullable=False)
    finished_at = Column(DateTime, nullable=True)
    disconnected_at = Column(DateTime, nullable=True)

    rounds = relationship("Round", back_populates="game")
