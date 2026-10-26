import logging

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    get_current_user_id,
    get_tutor_service,
    require_internal_api,
)
from app.core.exceptions import (
    ConfigurationError,
    ConversationAccessError,
    ConversationNotFoundError,
    GenerationError,
    RetrievalError,
)
from app.schemas.tutor import (
    InternalTutorRequest,
    InternalTutorResponse,
    TutorRequest,
    TutorResponse,
)
from app.services.tutor_service import TutorService

router = APIRouter(prefix="/tutor", tags=["tutor"])
internal_router = APIRouter(prefix="/tutor", tags=["internal-tutor"])
logger = logging.getLogger(__name__)


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
        raise HTTPException(
            status_code=403, detail="conversation access denied"
        ) from exc
    except GenerationError as exc:
        raise HTTPException(
            status_code=503, detail="answer generation is temporarily unavailable"
        ) from exc
    except (RetrievalError, ConfigurationError) as exc:
        raise HTTPException(
            status_code=503, detail="RAG retrieval is temporarily unavailable"
        ) from exc


@internal_router.post(
    "/answer",
    response_model=InternalTutorResponse,
    response_model_by_alias=True,
    dependencies=[Depends(require_internal_api)],
)
async def internal_answer(
    request: InternalTutorRequest,
    service: TutorService = Depends(get_tutor_service),
) -> InternalTutorResponse:
    logger.info(
        "internal tutor request",
        extra={
            "request_id": request.request_id,
            "conversation_id": request.conversation_id,
        },
    )
    try:
        return await service.answer_internal(request)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="conversation not found") from exc
    except ConversationAccessError as exc:
        raise HTTPException(
            status_code=403, detail="conversation access denied"
        ) from exc
    except (GenerationError, RetrievalError, ConfigurationError) as exc:
        raise HTTPException(
            status_code=503, detail="AI tutor is temporarily unavailable"
        ) from exc
