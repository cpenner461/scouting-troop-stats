"""Application configuration."""

import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Directory where troop .db files are stored
TROOP_DB_DIR = Path(os.environ.get("TROOP_DB_DIR", str(BASE_DIR)))

# App database (users, troops, memberships)
APP_DB_PATH = Path(os.environ.get("APP_DB_PATH", str(BASE_DIR / "app.db")))

# JWT settings
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_urlsafe(32))
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

# Password reset token validity
RESET_TOKEN_EXPIRE_MINUTES = 30
