from api import app as api
from database import session as db

if __name__ == "__main__":
    # initialization of the sqlite database
    db.initConnection() 

    # starts the uvicorn server (for FastAPI)
    api.runApp()
    
#EOF