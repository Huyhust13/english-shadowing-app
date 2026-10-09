"""Settings, read once from the environment at start-up.

Everything has a default that works for local development (`python -m hub`), so a
fresh checkout runs without any configuration. Production values come from the
systemd unit and ~/.config/english-hub/hub.env (see deploy/install-hub.sh).
"""
import os
import secrets

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _bool(name, default):
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


def _secret_key(data_dir):
    """SECRET_KEY from the environment, else a random one kept in the data folder."""
    if os.environ.get("SECRET_KEY"):
        return os.environ["SECRET_KEY"]
    path = os.path.join(data_dir, "secret_key")
    try:
        with open(path) as f:
            return f.read().strip()
    except FileNotFoundError:
        key = secrets.token_urlsafe(48)
        os.makedirs(data_dir, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(key)
        return key


class Config:
    def __init__(self, **overrides):
        data_dir = overrides.pop("DATA_DIR", None) or os.path.expanduser(
            os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data")))
        self.DATA_DIR = data_dir
        self.DATABASE = os.path.join(data_dir, "hub.db")
        self.USERS_DIR = os.path.join(data_dir, "users")          # per-user Anki collections
        self.WEB_DIR = os.path.join(BASE_DIR, "web")
        self.ICONS_DIR = os.path.join(BASE_DIR, "icons")

        self.HOST = os.environ.get("HOST", "127.0.0.1")
        self.PORT = int(os.environ.get("PORT", "8090"))
        # The address people open; used in reminder links and as the allowed Origin.
        self.PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{self.PORT}").rstrip("/")

        self.SECRET_KEY = None  # filled in below unless overridden (tests)
        self.SESSION_COOKIE_NAME = "hub_session"
        self.SESSION_COOKIE_HTTPONLY = True
        self.SESSION_COOKIE_SAMESITE = "Lax"
        self.SESSION_COOKIE_SECURE = self.PUBLIC_URL.startswith("https://")
        self.PERMANENT_SESSION_LIFETIME = 90 * 24 * 3600   # stay logged in for 90 days
        self.MAX_CONTENT_LENGTH = 2 * 1024 * 1024

        self.TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "Asia/Ho_Chi_Minh")

        # Background threads: Anki sync, reminders, Telegram bot. Off in tests.
        self.START_WORKERS = _bool("START_WORKERS", True)
        self.ANKI_ENABLED = _bool("ANKI_ENABLED", True)

        for key, value in overrides.items():
            setattr(self, key, value)
        if not self.SECRET_KEY:
            self.SECRET_KEY = _secret_key(self.DATA_DIR)
