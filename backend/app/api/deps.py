from flask import current_app, g, request
from sqlalchemy.orm import Session

_USER_HEADER = "X-User-Id"
_DEFAULT_USER_ID = "demo-user"


def get_session() -> Session:
    if "session" not in g:
        g.session = current_app.config["SESSION_FACTORY"]()
    return g.session


def teardown_session(exception: BaseException | None) -> None:
    session = g.pop("session", None)
    if session is not None:
        if exception is not None:
            session.rollback()
        session.close()


def current_user_id() -> str:
    return request.headers.get(_USER_HEADER, _DEFAULT_USER_ID)
