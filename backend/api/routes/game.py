import datetime
import re

from pydantic import BaseModel
from database import session as db
from fastapi import HTTPException

from api.app import getApp
from misc.functions import generate_game_code

from models.game_model import Game

app = getApp()

#
#   Returns an array with all the stored games if there are no parameters given
#   or returns an array with all the games filtered by the arguments
#

@app.get("/games")
async def list_games(page: int = 1, page_size: int = 10, code: str = None, game_state: str = None):
    session = db.getSession()
    
    # Filters
    query = session.query(Game)
    if game_state is not None:
        query = query.filter(Game.game_state == game_state)
    if code is not None:
        query = query.filter(Game.code == code)
    
    # Pagination stuff
    total_games = query.count()
    games = query.offset((page - 1) * page_size).limit(page_size).all()
    
    return {
        "total_games": total_games,
        "games": games,
    }

#
#   Creates a game and returns the created game ID and the join code
#   Requires a player name (3-16 characters)
#
class CreateGame(BaseModel):
    player1_name: str
    
@app.post("/game/create")
async def create_game(request: CreateGame):
    if len(request.player1_name) < 3 or len(request.player1_name) > 16:
        raise HTTPException(status_code=400, detail="Player name should be between 3 and 16 characters long.")
        
    pattern = r"^[a-zA-Z0-9_.]+$"
    if not re.match(pattern, request.player1_name):
        raise HTTPException(status_code=400, detail="Player name should contain only letters, number and special characters ('.' and '_')")

    session = db.getSession()

    code = generate_game_code()
    game = Game(
        code=code,
        player1_name=request.player1_name,
        player1_score=0,
        game_state="waiting",
        current_round=0
    )

    session.add(game)
    session.commit()
    session.refresh(game)

    return {"game_id": game.id, "code": game.code}

#
#   Gets data for a specific game by their ID
#

@app.get("/game/{game_id}")
async def get_game(game_id: str):
    game = db.getSession().query(Game).filter(Game.id == game_id).first()
    
    if not game:
        raise HTTPException(status_code=404, detail="Game not found.")

    return game

#
#   The method that allows the second player to join a lobby
#   Requires the join code and a player name
#

class JoinGame(BaseModel):
    code: str
    player_name: str

@app.post("/game/join")
async def join_game(request: JoinGame):
    if len(request.player_name) < 3 or len(request.player_name) > 16:
        raise HTTPException(status_code=400, detail="Player name should be between 3 and 16 characters long.")
        
    pattern = r"^[a-zA-Z0-9_.]+$"
    if not re.match(pattern, request.player_name):
        raise HTTPException(status_code=400, detail="Player name should contain only letters, number and special characters ('.' and '_')")

    session = db.getSession()
    game = session.query(Game).filter(Game.code == request.code).first()
    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found")

    if game.game_state != "waiting":
        raise HTTPException(status_code=403, detail="Game is already active!")

    # Updates the game with these values
    game.player2_name = request.player_name
    game.player2_score = 0
    game.game_state = "active"
    game.current_round = 1

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game
    
    return {
        "game_id": game.id,
        "player2_name": game.player2_name,
        "game_state": game.game_state,
    }

# class ChooseColor(BaseModel):
#     game_id: str
#     round_number: int
#     player_name: str
#     choice: str

# @app.post("/game/{game_id}/round/{round_number}/choice")
# async def choose_color(request: ChooseColor):
#     session = db.getSession()
#     game = session.query(Game).filter(Game.id == request.game_id).first()
#     if not game:
#         raise HTTPException(status_code = 404, detail = "Game not found")
#     if request.choice!="RED" or request.choice!="BLUE":
#         raise HTTPException(status_code = 400, detail = "Invalid choice")
    
#     if request.player_name == game.player1_name:
        
#     elif request.player_name == game.player2_name:

#
#   The method used for player reconnections
#   Should not reset the player's score, nor the current round of the game
#
class RejoinGame(BaseModel):
    player_name: str
    code: str

@app.post("/game/rejoin")
async def rejoin_game(request: RejoinGame):
    if len(request.player_name) < 3 or len(request.player_name) > 16:
        raise HTTPException(status_code=400, detail="Player name should be between 3 and 16 characters long.")
        
    pattern = r"^[a-zA-Z0-9_.]+$"
    if not re.match(pattern, request.player_name):
        raise HTTPException(status_code=400, detail="Player name should contain only letters, number and special characters ('.' and '_')")

    session = db.getSession()
    game = session.query(Game).filter(Game.code == request.code).first()
    
    if game.game_state != "waiting":
        raise HTTPException(status_code = 403, detail = "Both players are active")
    
    game.player2_name = request.player_name
    game.game_state = "active"

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game

    return{
        "response" : "Reconnected",
        "game_state" : game.game_state
    }

class AbandonGame(BaseModel):
    game_id: str
    player_name: str

@app.post("/game/{game_id}/abandon")
async def abandon_game(request: AbandonGame):
    session = db.getSession()
    game = session.query(Game).filter(Game.game_id == request.game_id).first()

    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found")
    
    if game.game_state != "active":
        raise HTTPException(status_code = 403, detail = "The game is not active")
    
    if request.player_name == game.player1_name:
        game.player1_score = -100
        game.player2_score = 100
    else:
        game.player1_score = 100
        game.player2_score = -100
    
    game.game_state = "finished"

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game

    return{
        "response": f"{game['player1_name'] if request['player_name'] == game['player1_name'] else game['player2_name']} abandoned the game!",
        "game_state" : game.game_state,
        "scores" : {
            game.player1_name:game.player1_score,
            game.player2_name:game.player2_score
        }
    }

class DisconnectGame(BaseModel):
    game_id: str

@app.post("/game/disconnect")
async def disconnect_game(request: DisconnectGame):
    session = db.getSession()
    game = session.query(Game).filter(Game.id == request.game_id).first()

    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found")
    if game.game_state != "active":
        raise HTTPException(status_code = 403, detail = "The game is not active")

    game.game_state = "waiting"
    game.disconnected_at = datetime.datetime.now(datetime.timezone.utc)

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game

    return {
        "message": "A player has disconnected!"
    }
    