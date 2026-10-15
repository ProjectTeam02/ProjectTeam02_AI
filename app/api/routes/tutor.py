from fastapi import APIRouter

from app.schemas.tutor import TutorRequest, TutorResponse
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/tutor", tags=["tutor"])
_service = TutorService()


@router.post("/chat", response_model=TutorResponse)
async def chat(request: TutorRequest) -> TutorResponse:
    return await _service.answer(request)
