import pytest

from hub import create_app, db, users
from hub.config import Config


@pytest.fixture
def app(tmp_path):
    config = Config(DATA_DIR=str(tmp_path), SECRET_KEY="test", START_WORKERS=False, ANKI_ENABLED=False,
                    PUBLIC_URL="https://hub.example", SESSION_COOKIE_SECURE=False)
    return create_app(config)


@pytest.fixture
def conn(app):
    c = db.connect(app.config["DATABASE"])
    yield c
    c.close()


@pytest.fixture
def make_user(conn):
    def make(username, admin=False, password="password123"):
        return users.create_user(conn, username, username.title(), password, "Asia/Ho_Chi_Minh", is_admin=admin)
    return make


def login(client, username, password="password123"):
    return client.post("/api/auth/login", json={"username": username, "password": password})
