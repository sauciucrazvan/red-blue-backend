import random
import string

# Used to generate random join codes for games
def generate_game_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=9))