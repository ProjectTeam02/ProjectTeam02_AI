from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.memory import router as memory_router
from app.api.routes.tutor import router as tutor_router

app = FastAPI(title="ProjectTeam02 AI API", version="0.1.0")

app.include_router(health_router)
app.include_router(tutor_router, prefix="/api")
app.include_router(memory_router, prefix="/api")
