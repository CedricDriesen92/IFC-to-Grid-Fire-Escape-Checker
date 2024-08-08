import os

# Flask settings
DEBUG = False
SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'

# File upload settings
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXTENSIONS = {'ifc', 'json'}
MAX_CONTENT_LENGTH = 1000 * 1024 * 1024  # 16 MB limit

# Ensure the upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Grid settings
DEFAULT_GRID_SIZE = 0.1

# Pathfinding settings
MAX_PATH_LENGTH = 1000  # Maximum number of steps in a path