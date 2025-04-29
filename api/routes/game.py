import datetime
import re

from pydantic import BaseModel
from ws.wsManager import notify_game_status
from database import session as db
from fastapi import HTTPException, Header

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

    return {"game_id": game.id, "code": game.code, "role": "player1", "token": game.player1_token}

#
#   Gets data for a specific game by their ID
#

from sqlalchemy.orm import joinedload

@app.get("/api/v1/game/{game_id}")
async def get_game(game_id: str, Authorization: str = Header(None)):
    session = db.getSession()
    game = session.query(Game).options(joinedload(Game.rounds)).filter(Game.id == game_id).first()

    if not game:
        raise HTTPException(status_code=404, detail="Game not found.")

    token = Authorization.split(" ")[1] if Authorization else None

    if token not in [game.player1_token, game.player2_token]:
        raise HTTPException(status_code=403, detail="Invalid token.")

    serialized_game = {
        "id": game.id,
        "code": game.code,
        "player1_name": game.player1_name,
        "player2_name": game.player2_name,
        "player1_score": game.player1_score,
        "player2_score": game.player2_score,
        "current_round": game.current_round,
        "game_state": game.game_state,
        "created_at": game.created_at,
        "disconnected_at": game.disconnected_at,
        "rounds": [
            {
                "round_number": r.round_number,
                "player1_choice": r.player1_choice,
                "player2_choice": r.player2_choice,
                "player1_score": r.player1_score,
                "player2_score": r.player2_score,
            }
            for r in game.rounds
        ]
    }

    return serialized_game

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
    token = None

    if not game.player1_name:
        game.player1_name = request.player_name
        game.player1_score = 0
        role = "player1"
        token = game.player1_token
    elif not game.player2_name:
        game.player2_name = request.player_name
        game.player2_score = 0
        role = "player2"
        token = game.player2_token
    else:
        raise HTTPException(status_code=400, detail="No available slot for the player.")

    game.game_state = "active"
    game.current_round = 1 if not game.current_round else game.current_round

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game
    
    await notify_game_status(
        game_id=game.id,
        status_update={
            "message": f"{request.player_name} joined the game", 
            "state": game.game_state,
            "player1_name": game.player1_name,
            "player2_name": game.player2_name
        }
    )

    return {
        "game_id": game.id,
        "player2_name": game.player2_name,
        "game_state": game.game_state,
        "role": role,
        "token": token,
    }

class ChooseColor(BaseModel):
    game_id: str
    round_number: int
    player_name: str
    choice: str 
    token: str

@app.post("/api/v1/game/{game_id}/round/{round_number}/choice")
async def choose_color(request: ChooseColor):
    session = db.getSession()
    game = session.query(Game).filter(Game.id == request.game_id).first()

    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    if game.game_state == "finished":
        raise HTTPException(status_code=403, detail="Game already finished!")

    if request.choice not in ["RED", "BLUE"]:
        raise HTTPException(status_code=400, detail="Invalid choice")

    if request.player_name == game.player1_name and request.token != game.player1_token:
        raise HTTPException(status_code=403, detail="Invalid token for player1.")
    elif request.player_name == game.player2_name and request.token != game.player2_token:
        raise HTTPException(status_code=403, detail="Invalid token for player2.")
    elif request.player_name not in [game.player1_name, game.player2_name]:
        raise HTTPException(status_code=400, detail="Player name does not match")

    round = next((r for r in game.rounds if r.round_number == request.round_number), None)

    if not round:
        round = Round(
            game_id=game.id,
            round_number=request.round_number,
            player1_choice=None,
            player2_choice=None,
            player1_score=0,
            player2_score=0
        )
        game.rounds.append(round)
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
        multiplier = 2 if round.round_number >= 9 else 1
        if round.player1_choice == "RED" and round.player2_choice == "RED":
            round.player1_score += 3 * multiplier
            round.player2_score += 3 * multiplier
        elif round.player1_choice == "BLUE" and round.player2_choice == "RED":
            round.player1_score += 6 * multiplier
            round.player2_score -= 6 * multiplier
        elif round.player1_choice == "RED" and round.player2_choice == "BLUE":
            round.player1_score -= 6 * multiplier
            round.player2_score += 6 * multiplier
        elif round.player1_choice == "BLUE" and round.player2_choice == "BLUE":
            round.player1_score -= 3 * multiplier
            round.player2_score -= 3 * multiplier

        game.player1_score += round.player1_score
        game.player2_score += round.player2_score
        game.current_round = round.round_number
        
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

            game.rounds.append(next_round)

            session.add(next_round)
            session.commit()
            session.refresh(next_round)

            await notify_game_status(
                game_id=game.id,
                status_update={
                    "message": f"Round {round.round_number} completed. Next round started!",

                    "player1_choice": round.player1_choice,
                    "player2_choice": round.player2_choice,
                    "player1_score": game.player1_score,
                    "player2_score": game.player2_score,

                    "next_round": next_round.round_number,
                }
            )
        else:
            game.game_state = "finished"
            session.commit()
            session.refresh(game)

            await notify_game_status(
                game_id=game.id,
                status_update={
                    "message": "Game over! All 10 rounds completed.",

                    "player1_choice": round.player1_choice,
                    "player2_choice": round.player2_choice,
                    "player1_score": game.player1_score,
                    "player2_score": game.player2_score,
                    
                    "game_state": game.game_state
                }
            )

    return {"message": "Choice registered successfully"}


#
#   In case one player abandons the game, their score will be set to 0
#   while the opponents will be set to 1, and the game is set to finished.
#

class AbandonGame(BaseModel):
    game_id: str
    player_name: str
    token: str

@app.post("/api/v1/game/{game_id}/abandon")
async def abandon_game(request: AbandonGame):

    session = db.getSession()
    game = session.query(Game).filter(Game.id == request.game_id).first()

    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found!")

    if game.game_state != "active":
        raise HTTPException(status_code = 403, detail = "The game is not active!")
    
    if request.player_name == game.player1_name and request.token != game.player1_token:
        raise HTTPException(status_code=403, detail="Invalid token for player1.")
    elif request.player_name == game.player2_name and request.token != game.player2_token:
        raise HTTPException(status_code=403, detail="Invalid token for player2.")

    round_diff = 10 - game.current_round

    for i in range(0, round_diff):
        multiplier = 2 if game.current_round >= 8 else 1
        
        game.current_round += 1

        next_round = Round(
                game_id=game.id,
                round_number=game.current_round,
                player1_choice=None,
                player2_choice=None,
                player1_score = (-6 * multiplier) if game.player1_name == request.player_name else 6 * multiplier,
                player2_score = (-6 * multiplier) if game.player2_name == request.player_name else 6 * multiplier,
            )        

        session.add(next_round)
        game.rounds.append(next_round)

        game.player1_score = game.player1_score + ((-6 * multiplier) if game.player1_name == request.player_name else 6 * multiplier)
        game.player2_score = game.player2_score + ((-6 * multiplier) if game.player2_name == request.player_name else 6 * multiplier)

        session.commit()
        session.refresh(game)
        session.refresh(next_round)

    game.player1_score = game.player1_score + ((-24) if game.player1_name == request.player_name else 0)
    game.player2_score = game.player2_score + ((-24) if game.player2_name == request.player_name else 0)

    game.game_state = "finished"

    session.commit()
    session.refresh(game)

    await notify_game_status(
        game_id=game.id,
        status_update={
            "message": f"{request.player_name} abandoned the game.",
            "game_state": "finished",
            "player1_score": game.player1_score,
            "player2_score": game.player2_score,
        }
    )

    return {
        "response": f"{game['player1_name'] if request['player_name'] == game['player1_name'] else game['player2_name']} abandoned the game!",
        "game_state" : game.game_state,
    }

#
#   The API method used for players that disconnect from the game
#

# class DisconnectGame(BaseModel):
#     game_id: str
#     player_name: str

# @app.post("/api/v1/game/disconnect")
# async def disconnect_game(request: DisconnectGame):
#     session = db.getSession()
#     game = session.query(Game).filter(Game.id == request.game_id).first()

#     if not game:
#         raise HTTPException(status_code = 404, detail = "Game not found!")
    
#     if game.game_state == "finished":
#         raise HTTPException(status_code = 403, detail = "The game is already finished!")
    
#     if request.player_name == game.player1_name:
#         game.player1_name = ""
#     elif request.player_name == game.player2_name:
#         game.player2_name = ""
#     else:
#         raise HTTPException(status_code = 400, detail = "No player connected with that username!")
    
#     if not game.player1_name and not game.player2_name: #both disconnected
#         game.game_state = "finished"
#     else:
#         game.game_state = "waiting"
#         game.disconnected_at = datetime.datetime.now(datetime.timezone.utc)

#     session.commit() # Commits the changes to the database
#     session.refresh(game) # Updates the game

#     return {
#         "message": f"{request.player_name} disconnected from the game!",
#         "game_state": game.game_state,
#     }
    