"""English Hub: a small multi-user web app for daily English practice.

create_app() is the application factory: it builds the Flask app from a Config,
wires the shared services (Anki pool, notifications, Telegram bot, reminders) and
registers one blueprint per area of the API. See docs/ARCHITECTURE.md.
"""
import logging
from dataclasses import dataclass

from flask import Flask, current_app, jsonify
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import db, security
from .anki_pool import AnkiPool
from .config import Config
from .notify import Notifier, PushChannel, TelegramAPI, TelegramChannel
from .reminders import ReminderService
from .telegram_bot import TelegramBot

__version__ = "3.0.0"


@dataclass
class Services:
    pool: AnkiPool
    notifier: Notifier
    telegram: TelegramChannel
    push: PushChannel
    bot: TelegramBot | None
    reminders: ReminderService


def services() -> Services:
    return current_app.extensions["hub"]


def create_app(config=None):
    config = config or Config()
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config)
    # Tailscale Funnel (or any reverse proxy) sits in front; trust one hop of X-Forwarded-*.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.migrate(config.DATABASE)
    app.teardown_appcontext(db.close_db)
    app.before_request(security.load_user)
    app.before_request(security.check_same_origin)
    app.extensions["rate_limits"] = {name: security.RateLimiter(**limits)
                                     for name, limits in security.RATE_LIMITS.items()}

    tg_api = TelegramAPI(config.TELEGRAM_BOT_TOKEN) if config.TELEGRAM_BOT_TOKEN else None
    telegram = TelegramChannel(config.DATABASE, tg_api)
    push = PushChannel(config.DATABASE, config.DATA_DIR, subject=config.PUBLIC_URL)
    pool = AnkiPool(config.DATABASE, config.USERS_DIR)
    if not config.ANKI_ENABLED:
        pool.available, pool.error = False, "turned off (ANKI_ENABLED=0)"
    notifier = Notifier([telegram, push])
    app.extensions["hub"] = Services(
        pool=pool, notifier=notifier, telegram=telegram, push=push,
        bot=TelegramBot(config.DATABASE, tg_api, config.PUBLIC_URL) if tg_api else None,
        reminders=ReminderService(config.DATABASE, pool, notifier, config.PUBLIC_URL),
    )

    from .routes import admin, anki, api, auth, me, pages
    for module in (pages, auth, api, anki, me, admin):
        app.register_blueprint(module.bp)

    @app.errorhandler(HTTPException)
    def http_error(e):
        return jsonify(error=e.description), e.code

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        return resp

    if config.START_WORKERS:
        start_workers(app)
    return app


def start_workers(app):
    svc = app.extensions["hub"]
    if svc.pool.available:
        svc.pool.start()
    if svc.bot:
        svc.bot.start()
    svc.reminders.start()
    logging.getLogger(__name__).info(
        "workers started (anki=%s, telegram=%s, push=%s)",
        svc.pool.available, svc.bot is not None, svc.push.available)
