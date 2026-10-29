from fastapi import FastAPI

from app.api.v1.routers.health import router as health_router
from app.api.v1.routers.memory import router as memory_router
from app.api.v1.routers.tutor import internal_router
from app.api.v1.routers.tutor import router as tutor_router

app = FastAPI(title="Leren에 오신걸 환영합니다", version="0.1.0")

app.include_router(health_router)
app.include_router(tutor_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
app.include_router(internal_router, prefix="/internal/v1")


@app.get("/")
def root() -> dict[str, str]:
    return {"status": "success", "message": "Leren AI Server is running!"}
