import uuid as uuid

from database import session as db

from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship

Base = db.getBase()

class Round(Base):
    __tablename__ = 'rounds'
    id = Column(String, primary_key=True, nullable=False, default = lambda: str(uuid.uuid4()))
    game_id = Column(String, nullable = False)

    round_number = Column(Integer, nullable = False)

    player1_choice = Column(String, nullable=True)
    player2_choice = Column(String, nullable=True)
    player1_score = Column(Integer, nullable=True)
    player2_score = Column(Integer, nullable=True)

    game = relationship("Game", back_populates="rounds")
    