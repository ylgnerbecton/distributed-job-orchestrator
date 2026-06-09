from collections.abc import Callable

from flask import Flask
from flask_cors import CORS
from flask_smorest import Api
from sqlalchemy.orm import Session

from app.api.blueprints.health import health_blueprint
from app.api.blueprints.jobs import jobs_blueprint
from app.api.deps import teardown_session
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.session import session_factory as default_session_factory
from app.queue.redis_queue import JobQueue, create_queue

_SWAGGER_UI_CDN = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
_ALLOWED_HEADERS = ["Content-Type", "X-User-Id", "Idempotency-Key"]


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
    queue: JobQueue | None = None,
) -> Flask:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = Flask(__name__)
    app.config["API_TITLE"] = "Distributed Job Orchestrator"
    app.config["API_VERSION"] = "0.1.0"
    app.config["OPENAPI_VERSION"] = "3.0.3"
    app.config["OPENAPI_URL_PREFIX"] = "/"
    app.config["OPENAPI_JSON_PATH"] = "openapi.json"
    app.config["OPENAPI_SWAGGER_UI_PATH"] = "/docs"
    app.config["OPENAPI_SWAGGER_UI_URL"] = _SWAGGER_UI_CDN
    app.config["PROPAGATE_EXCEPTIONS"] = True
    app.config["SESSION_FACTORY"] = session_factory or default_session_factory
    app.config["JOB_QUEUE"] = queue or create_queue()
    app.config["APP_SETTINGS"] = settings

    CORS(
        app,
        origins=[origin.strip() for origin in settings.frontend_origin.split(",")],
        allow_headers=_ALLOWED_HEADERS,
    )

    api = Api(app)
    api.register_blueprint(health_blueprint)
    api.register_blueprint(jobs_blueprint)

    app.teardown_appcontext(teardown_session)
    return app
