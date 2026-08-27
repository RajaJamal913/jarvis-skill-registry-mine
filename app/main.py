import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.database import Base, engine
from app.routers import skills, departments, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Evaluation/dev convenience. In a real deployment this is replaced by
    # `alembic upgrade head` (see /alembic) and AUTO_CREATE_SCHEMA=0.
    if os.getenv("AUTO_CREATE_SCHEMA", "1") == "1":
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Jarvis AI COO - Organization-Scoped Skill Registry",
    description=(
        "Vertical slice: multi-tenant skill drafting, review, immutable "
        "versioning, owner-only activation, and audit logging."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


def _jsonable_errors(errors: list[dict]) -> list[dict]:
    cleaned = []
    for err in errors:
        e = dict(err)
        ctx = e.get("ctx")
        if isinstance(ctx, dict):
            e["ctx"] = {k: str(v) for k, v in ctx.items()}
        cleaned.append(e)
    return cleaned


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": "Invalid request.", "errors": _jsonable_errors(exc.errors())},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(skills.router)
app.include_router(departments.router)
app.include_router(audit.router)
