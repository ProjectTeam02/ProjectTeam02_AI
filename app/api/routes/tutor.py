from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_user_id, get_tutor_service
from app.core.exceptions import ConversationAccessError, ConversationNotFoundError, GenerationError
from app.schemas.tutor import TutorRequest, TutorResponse
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/tutor", tags=["tutor"])


@router.post("/chat", response_model=TutorResponse)
async def chat(
    request: TutorRequest,
    current_user_id: str = Depends(get_current_user_id),
    service: TutorService = Depends(get_tutor_service),
) -> TutorResponse:
    try:
        return await service.answer(request, authenticated_user_id=current_user_id)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    except ConversationAccessError as exc:
        raise HTTPException(status_code=403, detail="conversation access denied") from exc
    except GenerationError as exc:
        raise HTTPException(status_code=503, detail="answer generation is temporarily unavailable") from exc
