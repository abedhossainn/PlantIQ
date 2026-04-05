"""Pipeline API router — assembles sub-routers into a single APIRouter."""
from fastapi import APIRouter, Depends

from ...core.security import require_admin
from ._routes_decisions import router as decisions_router
from ._routes_list import router as list_router
from ._routes_publish import router as publish_router
from ._routes_review import router as review_router
from ._routes_upload import router as upload_router

router = APIRouter(prefix="/api/v1", tags=["Pipeline"], dependencies=[Depends(require_admin)])
router.include_router(list_router)
router.include_router(upload_router)
router.include_router(review_router)
router.include_router(decisions_router)
router.include_router(publish_router)
