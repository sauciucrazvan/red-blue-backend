import asyncio
import datetime
import re
 
from pydantic import BaseModel
from core import config
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
async def list_games(
    page: int = 1,
    page_size: int = 10,
    admin_token: str = None,
    game_state: str = None
):
    if admin_token != config.admin_token:
        raise HTTPException(status_code=403, detail="Invalid admin token.")
    
    if page < 1:
        raise HTTPException(status_code=400, detail="Page must be greater than 0.")

    from sqlalchemy.orm import joinedload
    from sqlalchemy import case

    session = db.getSession()
    dbGames = session.query(Game)

    if game_state:
        dbGames = dbGames.filter(Game.game_state == game_state)

    games = dbGames.options(joinedload(Game.rounds)).order_by(
        case((Game.game_state == "active", 0), else_=1),
        Game.created_at.desc()
    ).offset((page - 1) * page_size).limit(page_size).all()
    total_games_size = dbGames.count()

    result = {
        "page": page,
        "page_size": page_size,
        "found_games": total_games_size,
        "games": [
            {
                "id": game.id,
                "code": game.code,
                "player1_name": game.player1_name,
                "player2_name": game.player2_name,
                "player1_score": game.player1_score,
                "player2_score": game.player2_score,
                "player1_disconnected_at": game.player1_disconnected_at,
                "player2_disconnected_at": game.player2_disconnected_at,
                "current_round": len(game.rounds),
                "game_state": game.game_state,
                "created_at": game.created_at,
                "finished_at": game.finished_at,
                "rounds": [
                    {
                        "round_number": r.round_number,
                        "player1_choice": r.player1_choice,
                        "player2_choice": r.player2_choice,
                        "player1_score": r.player1_score,
                        "player2_score": r.player2_score,
                        "created_at": r.created_at,
                    }
                    for r in game.rounds
                ]
            }
            for game in games
        ]
    }
    session.close()
    return result
 
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
        created_at=datetime.datetime.now(datetime.timezone.utc)
    )
 
    session.add(game)
    session.commit()
    session.refresh(game)

    asyncio.create_task(start_lobby_expire_timer(game.id))
    return {"game_id": game.id, "code": game.code, "role": "player1", "token": game.player1_token}
 
async def start_lobby_expire_timer(game_id: int):
    expire_time = 600
    if config.debug:
        expire_time = 60
    
    await asyncio.sleep(expire_time)

    session = db.getSession()
    game = session.query(Game).filter(Game.id == game_id).first()

    if not game:
        session.close()
        return

    if game.current_round >= 1 or game.game_state != "waiting":
        return
    
    session.query(Game).filter(Game.id == game_id).delete()
    if config.debug:
        print(f"[LOGS]: Destroyed lobby {game_id} due to inactivity.")

    session.commit()

    session.close()

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
        "player1_disconnected_at": game.player1_disconnected_at,
        "player2_disconnected_at": game.player2_disconnected_at,
        "current_round": len(game.rounds),
        "game_state": game.game_state,
        "created_at": game.created_at,
        "finished_at": game.finished_at,
        "rounds": [
            {
                "round_number": r.round_number,
                "player1_choice": r.player1_choice,
                "player2_choice": r.player2_choice,
                "player1_score": r.player1_score,
                "player2_score": r.player2_score,
                "created_at": r.created_at,
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
 
    if game.game_state == "finished" or game.game_state == "abandoned":
        raise HTTPException(status_code=403, detail="Game already finished!")

    if game.player1_name == request.player_name or game.player2_name == request.player_name:
            raise HTTPException(status_code=403, detail="There is already a player with that name playing right now!")
 
    if game.game_state == "active" and game.player1_name and game.player2_name:
        raise HTTPException(status_code=403, detail="Both players are active.")
 
    role = None
    token = None
 
    if not game.player1_name:
        game.player1_name = request.player_name
        game.player1_score = game.player1_score if game.player1_score else 0
        game.player1_disconnected_at = None
        role = "player1"
        token = game.player1_token
    elif not game.player2_name:
        game.player2_name = request.player_name
        game.player2_score = game.player2_score if game.player2_score else 0
        game.player2_disconnected_at = None
        role = "player2"
        token = game.player2_token
    else:
        raise HTTPException(status_code=400, detail="No available slot for the player.")
 
    if game.player1_name and game.player2_name:
        game.game_state = "active"
        game.current_round = 1 if not game.current_round else game.current_round

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game
 
    await notify_game_status(
        game_id=game.id,
        status_update={
            "message": f"{request.player_name} joined the game", 
            "game_state": game.game_state,
            "current_round": game.current_round,
            "player1_name": game.player1_name,
            "player2_name": game.player2_name
        }
    )
 
    if game.player1_name and game.player2_name and game.current_round:
        existing_round = next((r for r in game.rounds if r.round_number == game.current_round), None)
        if not existing_round:
            round = Round(
                game_id=game.id,
                round_number=game.current_round,
                player1_choice=None,
                player2_choice=None,
                player1_score=0,
                player2_score=0
            )
            game.rounds.append(round)
            session.add(round)
            session.commit()
            session.refresh(round)
        asyncio.create_task(start_round_timer(game.id, game.current_round))
 
    return {
        "game_id": game.id,
        "player1_name": game.player1_name,
        "player2_name": game.player2_name,
        "player1_score": game.player1_score,
        "player2_score": game.player2_score,
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
 
    if game.game_state != "active":
        raise HTTPException(status_code=403, detail="The game is not active")
 
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
            player2_score=0,
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
            game.current_round = round.round_number + 1
 
            session.add(next_round)
            session.commit()
            session.refresh(next_round)
 
            asyncio.create_task(start_round_timer(game.id, next_round.round_number))
 
            await notify_game_status(
                game_id=game.id,
                status_update={
                    "message": f"Round {round.round_number} completed. Next round started!",
 
                    "player1_choice": round.player1_choice,
                    "player2_choice": round.player2_choice,
                    "player1_score": game.player1_score,
                    "player2_score": game.player2_score,
 
                    "next_round": next_round.round_number,
                    "rounds": [
                        {
                            "round_number": r.round_number,
                            "player1_choice": r.player1_choice,
                            "player2_choice": r.player2_choice,
                            "player1_score": r.player1_score,
                            "player2_score": r.player2_score,
                            "created_at": r.created_at,
                        }
                        for r in game.rounds
                    ]
                }
            )
        else:
            game.game_state = "finished"
            game.finished_at = datetime.datetime.now(datetime.timezone.utc)
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

async def start_round_timer(game_id: int, round_number: int):
    await asyncio.sleep(60)
 
    session = db.getSession()
    game = session.query(Game).filter(Game.id == game_id, Game.game_state == "active").first()
 
    if not game:
        session.close()
        return
 
    round = next((r for r in game.rounds if r.round_number == round_number), None)
    if not round:
        session.close()
        return
 
    if not round.player1_choice and not round.player2_choice:
        game.game_state = "finished"
 
        game.player1_score = 0
        game.player2_score = 0
 
        session.commit()
        session.refresh(game)
 
        await notify_game_status(
            game_id=game.id,
            status_update={
                "message": f"Game ended: no choices made by either player in round {round_number}.",
                "game_state": game.game_state,
                "player1_score": game.player1_score,
                "player2_score": game.player2_score
            }
        )
 
        session.close()
        return
 
    if round.player1_choice and not round.player2_choice:
        abandoning_player = game.player2_name
        token = game.player2_token
    elif round.player2_choice and not round.player1_choice:
        abandoning_player = game.player1_name
        token = game.player1_token
    else:
        session.close()
        return
 
    fake_request = AbandonGame(
        game_id=game.id,
        player_name=abandoning_player,
        token=token
    )
    await abandon_game(fake_request)
 
    session.close()
 
 
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
 
    game.game_state = "abandoned"
 
    session.commit()
    session.refresh(game)
 
    await notify_game_status(
        game_id=game.id,
        status_update={
            "message": f"{request.player_name} abandoned the game.",
            "game_state": game.game_state,
            "player1_score": game.player1_score,
            "player2_score": game.player2_score,
        }
    )
 
    return {
        "response": f"{request.player_name} abandoned the game!",
        "game_state" : game.game_state,
    }
 
#
#   Deletes a game by its ID if its in "waiting" state
#
 
@app.delete("/api/v1/game/{game_id}/delete")
async def delete_game(game_id: str, Authorization: str = Header(None)):
    session = db.getSession()
    game = session.query(Game).filter(Game.id == game_id).first()
 
    if not game:
        raise HTTPException(status_code=404, detail="Game not found.")
 
    if game.game_state != "waiting":
        raise HTTPException(status_code=403, detail="Game cannot be deleted. It is already in progress.")
 
    token = Authorization.split(" ")[1] if Authorization else None
 
    if token not in [game.player1_token, game.player2_token]:
        raise HTTPException(status_code=403, detail="Invalid token.")
 
 
    session.delete(game)
    session.commit()
    session.close()
 
    if config.debug:
        print(f"[LOGS]: Destroyed lobby {game_id} by request.")
 
    return {"message": "Game deleted successfully."}


#
#   The API method used for players that disconnect from the game
#
 
class DisconnectGame(BaseModel):
    game_id: str
    player_name: str
    token: str
 
@app.post("/api/v1/game/{game_id}/disconnect")
async def disconnect_game(request: DisconnectGame):
    print(f"Starting: [disconnect event on game: {request.game_id}, player_name: {request.player_name}]")

    session = db.getSession()
    game = session.query(Game).filter(Game.id == request.game_id).first()

    if not game:
        raise HTTPException(status_code = 404, detail = "Game not found!")

    if game.game_state == "waiting" or game.game_state == "finished" or game.game_state == "abandoned":
        raise HTTPException(status_code = 403, detail = "The game is not active!")
    
    if request.player_name == game.player1_name and game.player1_disconnected_at:
        raise HTTPException(status_code = 403, detail = "Player1 already disconnected!")
    if request.player_name == game.player2_name and game.player2_disconnected_at:
        raise HTTPException(status_code = 403, detail = "Player2 already disconnected!")
    
    if request.player_name == game.player1_name and request.token != game.player1_token:
        raise HTTPException(status_code=403, detail="Invalid token for player1.")
    elif request.player_name == game.player2_name and request.token != game.player2_token:
        raise HTTPException(status_code=403, detail="Invalid token for player2.")
    elif request.player_name not in [game.player1_name, game.player2_name]:
        raise HTTPException(status_code=400, detail="Player name does not match")

    if game.rounds:
        last_round = sorted(game.rounds, key=lambda r: r.round_number)[-1]
        if not (last_round.player1_choice and last_round.player2_choice):
            session.delete(last_round)
            game.rounds.remove(last_round)

    await notify_game_status(
        game_id=game.id,
        status_update={
            "message": f"{request.player_name} left the game. Waiting for him to join back...",
            "game_state": game.game_state,
        }
    )

    session.query(Game).filter(Game.id == request.game_id).update({
        "player1_name": None if request.player_name == game.player1_name else game.player1_name,
        "player2_name": None if request.player_name == game.player2_name else game.player2_name,
        "player1_disconnected_at": datetime.datetime.now(datetime.timezone.utc) if request.player_name == game.player1_name else game.player1_disconnected_at,
        "player2_disconnected_at": datetime.datetime.now(datetime.timezone.utc) if request.player_name == game.player2_name else game.player2_disconnected_at,
        "game_state": "pause" if game.player1_name or game.player2_name else "finished",
        "current_round": game.current_round,
    })

    session.commit() # Commits the changes to the database
    session.refresh(game) # Updates the game

    asyncio.create_task(check_disconnection_timer(game.id))

    print(f"Ending: [disconnect event on game: {request.game_id}]")

    return {
        "message": f"{request.player_name} disconnected from the game!",
        "game_state": game.game_state,
    }

async def check_disconnection_timer(game_id: str):
    time = 600
    if config.debug:
        time = 60

    await asyncio.sleep(time + 10)

    session = db.getSession()
    game = session.query(Game).filter(Game.id == game_id).first()

    if not game:
        session.close()
        return

    if game.game_state != "pause":
        session.close()
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    if game.player1_disconnected_at:
        player1_disconnected_at = game.player1_disconnected_at
        if player1_disconnected_at.tzinfo is None:
            player1_disconnected_at = player1_disconnected_at.replace(tzinfo=datetime.timezone.utc)
        if (now - player1_disconnected_at).total_seconds() > time:
            await notify_game_status(
                game_id=game.id,
                status_update={
                    "message": f"{game.player1_name} has been disconnected for more than 10 minutes. Game will be deleted.",
                    "game_state": "finished",
                }
            )
            
            for r in list(game.rounds):
                session.delete(r)

            session.delete(game)
            
            session.commit()
            session.close()
            return

    if game.player2_disconnected_at:
        player2_disconnected_at = game.player2_disconnected_at
        if player2_disconnected_at.tzinfo is None:
            player2_disconnected_at = player2_disconnected_at.replace(tzinfo=datetime.timezone.utc)
        if (now - player2_disconnected_at).total_seconds() > time:
            await notify_game_status(
                game_id=game.id,
                status_update={
                    "message": f"{game.player2_name} has been disconnected for more than 10 minutes. Game will be deleted.",
                    "game_state": "finished",
                }
            )
            
            for r in list(game.rounds):
                session.delete(r)

            session.delete(game)
            session.commit()
            session.close()
            return