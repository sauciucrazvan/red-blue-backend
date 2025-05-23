import uuid


debug = True

# Uvicorn server
uvicorn_host = "localhost"
uvicorn_port = 8000

admin_password = "admin"
admin_token = uuid.uuid4().hex # resets every time the server is restarted