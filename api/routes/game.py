import datetime
import re

from pydantic import BaseModel
from ws.wsManager import notify_game_status
from database import session as db
from fastapi import HTTPException

from api.app import getApp
from misc.functions import generate_game_code

from models.game_model import Game
from models.round_model import Round

app = getApp()

#
#   Returns an array with all the stored games if there are no parameters given
#   or returns an array with all the games filtered by the arguments
#

@app.get("/api/v1/games")
async def list_games(page: int = 1, page_size: int = 10):
    games = db.getSession().query(Game).offset((page - 1) * page_size).limit(page_size).all()
    return games

#
#   Creates a game and returns the created game ID and the join code
#   Requires a player name (3-16 characters)
#
class CreateGame(BaseModel):
    player1_name: str
    
@app.post("/api/v1/game/create")
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
        current_round=0,
        current_round_id=None,
    )

    session.add(game)
    session.commit()
    session.refresh(game)

    return {"game_id": game.id, "code": game.code, "role": "player1"}

#
#   Gets data for a specific game by their ID
#

@app.get("/api/v1/game/{game_id}")
async def get_game(game_id: str):
    game = db.getSession().query(Game).filter(Game.id == game_id).first()
    
    if not game:
        raise HTTPException(status_code=404, detail="Game not found.")

    return game

#
#   The method that allows the second player to join a lobby
#   Requires the join code and a player name. Players will rejoin using this method.
#

class JoinGame(BaseModel):
    code: str
    player_name: str

@app.post("/api/v1/game/join")
async def join_game(request: JoinGame):
    if len(request.player_name) < 3 or len(request.player_name) > 16:
        raise HTTPException(status_code=400, detail="Player name should be between 3 and 16 characters long.")
        
    pattern = r"^[a-zA-Z0-9_.]+$"
    if not re.match(pattern, request.player_name):
        raise HTTPException(status_code=400, detail="Player name should contain only letters, number and special characters ('.' and '_')")

    session = db.getSession()
    game = session.query(Game).filter(Game.code == request.code).first()
    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found!")

    if game.player1_name == request.player_name or game.player2_name == request.player_name:
            raise HTTPException(status_code=403, detail="There are no free slots available.")

    if game.game_state == "active" and game.player1_name and game.player2_name:
        raise HTTPException(status_code=403, detail="Both players are active.")
    
    role = None

    if not game.player1_name:
        game.player1_name = request.player_name
        game.player1_score = 0
        role = "player1"
    elif not game.player2_name:
        game.player2_name = request.player_name
        game.player2_score = 0
        role = "player2"
    else:
        raise HTTPException(status_code=400, detail="No available slot for the player.")

    game.game_state = "active"
    game.current_round = 1 if not game.current_round else game.current_round

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game
    
    await notify_game_status(
        game_id=game.id,
        status_update={"message": f"{request.player_name} joined the game", "state": game.game_state}
    )

    return {
        "game_id": game.id,
        "player2_name": game.player2_name,
        "game_state": game.game_state,
        "role": role,
    }

class ChooseColor(BaseModel):
    game_id: str
    round_number: int
    player_name: str
    choice: str 

@app.post("/game/{game_id}/round/{round_number}/choice")
async def choose_color(request: ChooseColor):
    session = db.getSession()
    game = session.query(Game).filter(Game.id == request.game_id).first()
    
    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found")
    
    if request.choice != "RED" and request.choice != "BLUE":
        raise HTTPException(status_code = 400, detail = "Invalid choice")

    round = session.query(Round).filter(Round.game_id == game.id, Round.round_number == request.round_number).first()

    if not round:
        round = Round(
            game_id=game.id,
            round_number=request.round_number,
            player1_choice=None,
            player2_choice=None,
            player1_score=0,
            player2_score=0
        )
        session.add(round)
        session.commit()


    if request.player_name == game.player1_name:
        if round.player1_choice:
            raise HTTPException(status_code=400, detail="Already chose a color")
        
        round.player1_choice = request.choice
    elif request.player_name == game.player2_name:
        if round.player2_choice:
            raise HTTPException(status_code=400, detail="Already chose a color")
        
        round.player2_choice = request.choice
    else:
        raise HTTPException(status_code=400, detail="Player name does not match")
    
    session.commit()
    session.refresh(game)

    if round.player1_choice and round.player2_choice:
        if round.player1_choice == "RED" and round.player2_choice == "RED":
            round.player1_score += 3
            round.player2_score += 3
        elif round.player1_choice == "BLUE" and round.player2_choice == "RED":
            round.player1_score += 6
            round.player2_score -= 6
        elif round.player1_choice == "RED" and round.player2_choice == "BLUE":
            round.player1_score -= 6
            round.player2_score += 6
        elif round.player1_choice == "BLUE" and round.player2_choice == "BLUE":
            round.player1_score -= 3
            round.player2_score -= 3
        game.player1_score += round.player1_score
        game.player2_score += round.player2_score
        session.commit()
        session.refresh(round)
        session.refresh(game)
        if round.round_number < 10:
            next_round = Round(
                game_id=game.id,
                round_number=round.round_number + 1,
                player1_choice=None,
                player2_choice=None,
                player1_score=0,
                player2_score=0
            )
            session.add(next_round)
            session.commit()
            session.refresh(next_round)

            await notify_game_status(
                game_id=game.id,
                status_update={
                    "message": f"Round {round.round_number} completed. Next round started!",
                    "player1_choice": round.player1_choice,
                    "player2_choice": round.player2_choice,
                    "next_round": next_round.round_number,
                    "player1_score": game.player1_score,
                    "player2_score": game.player2_score
                }
            )
        else:
            await notify_game_status(
                game_id=game.id,
                status_update={
                    "message": "Game over! All 10 rounds completed.",
                    "player1_choice": round.player1_choice,
                    "player2_choice": round.player2_choice,
                    "player1_score": game.player1_score,
                    "player2_score": game.player2_score
                }
            )
    else:
        await notify_game_status(
            game_id=game.id,
            status_update={
                "message": f"{request.player_name} chose {request.choice}",
                "player1_choice": round.player1_choice,
                "player2_choice": round.player2_choice
            }
        )


    return {"message": "Choice registered successfully"}
#
#   In case one player abandons the game, their score will be set to -100
#   while the opponents will be set to 100, and the game is set to finished.
#

class AbandonGame(BaseModel):
    game_id: str
    player_name: str

@app.post("/api/v1/game/{game_id}/abandon")
async def abandon_game(request: AbandonGame):

    session = db.getSession()
    game = session.query(Game).filter(Game.game_id == request.game_id).first()

    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found!")
    if game.game_state != "active":
        raise HTTPException(status_code = 403, detail = "The game is not active!")
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

#
#   The API method used for players that disconnect from the game
#

class DisconnectGame(BaseModel):
    game_id: str
    player_name: str

@app.post("/api/v1/game/disconnect")
async def disconnect_game(request: DisconnectGame):
    session = db.getSession()
    game = session.query(Game).filter(Game.id == request.game_id).first()

    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found!")
    
    if game.game_state == "finished":
        raise HTTPException(status_code = 403, detail = "The game is already finished!")
    
    if request.player_name == game.player1_name:
        game.player1_name = ""
    elif request.player_name == game.player2_name:
        game.player2_name = ""
    else:
        raise HTTPException(status_code = 400, detail = "No player connected with that username!")
    
    if not game.player1_name and not game.player2_name: #both disconnected
        game.game_state = "finished"
    else:
        game.game_state = "waiting"
        game.disconnected_at = datetime.datetime.now(datetime.timezone.utc)

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game

    return {
        "message": f"{request.player_name} disconnected from the game!",
        "game_state": game.game_state,
    }
    