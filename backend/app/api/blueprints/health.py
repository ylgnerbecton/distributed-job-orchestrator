from flask import current_app
from flask.views import MethodView
from flask_smorest import Blueprint
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import get_session
from app.schemas.common import HealthSchema

health_blueprint = Blueprint("health", "health", url_prefix="/health", description="Liveness and dependency checks")


@health_blueprint.route("")
class Health(MethodView):
    @health_blueprint.response(200, HealthSchema)
    def get(self) -> dict:
        return {"status": "ok", "database": _database_status(), "queue": _queue_status()}


def _database_status() -> str:
    try:
        get_session().execute(text("SELECT 1"))
    except SQLAlchemyError:
        return "down"
    return "ok"


def _queue_status() -> str:
    try:
        return "ok" if current_app.config["JOB_QUEUE"].ping() else "down"
    except RedisError:
        return "down"
