from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    database: str
    queue: str


class ErrorResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    message: str
