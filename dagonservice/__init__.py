"""DAGonService: registration and remote monitoring of DAGonStar workflows."""

from __future__ import annotations

import logging
from typing import Any, Optional

from flask import Flask, jsonify, render_template

__version__ = "2.0.0"


def create_app(settings: Optional[Any] = None, database: Optional[Any] = None) -> Flask:
    """Application factory.

    :param settings: a :class:`dagonservice.config.Settings`; read from the
        environment when omitted.
    :param database: a ``pymongo.database.Database`` (or a ``mongomock`` one in
        tests); opened from ``settings.mongo_uri`` when omitted.
    """
    from .api import legacy, register_error_handlers, v1
    from .config import Settings
    from .notifier import WebhookNotifier
    from .storage import WorkflowStore

    settings = settings or Settings.from_env()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if database is None:
        from pymongo import MongoClient

        client: Any = MongoClient(settings.mongo_uri, tz_aware=True, connect=False,
                                  serverSelectionTimeoutMS=5000)
        database = client[settings.db_name]

    store = WorkflowStore(database, max_history=settings.max_history)
    try:
        store.ensure_indexes()
    except Exception as exc:  # the database may still be starting; indexes are an optimisation
        logging.getLogger(__name__).warning("Could not create indexes yet: %s", exc)
    notifier = WebhookNotifier(settings.webhook_urls, timeout=settings.webhook_timeout)
    if notifier.enabled:
        store.on_event = notifier.publish

    app = Flask(__name__)
    app.json.sort_keys = False
    app.extensions["dagonservice.settings"] = settings
    app.extensions["dagonservice.store"] = store
    app.extensions["dagonservice.notifier"] = notifier

    register_error_handlers(app)

    @app.route("/", methods=["GET"])
    def index():
        if settings.dashboard:
            return render_template("dashboard.html", version=__version__,
                                   refresh_ms=settings.dashboard_refresh_ms,
                                   protect_reads=settings.protect_reads and settings.api_token is not None)
        return jsonify({"service": "DAGonService", "version": __version__, "api": "/api/v1"})

    app.register_blueprint(v1)
    app.register_blueprint(legacy)  # last: it owns the catch-all /<workflow_id> routes

    @app.cli.command("upgrade-documents")
    def upgrade_documents() -> None:
        """Convert workflow documents of the 2018 prototype to schema version 2."""
        from .migrate import upgrade_all
        from .model import SCHEMA_VERSION

        count = upgrade_all(database)
        print("Upgraded %d workflow document(s) to schema version %d." % (count, SCHEMA_VERSION))

    @app.after_request
    def _security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if response.mimetype == "text/html":
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        return response

    return app
