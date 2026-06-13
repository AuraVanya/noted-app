from fastapi import APIRouter, HTTPException, status


router = APIRouter(prefix="/api/auth/atlassian", tags=["auth"])


@router.get("/login")
async def atlassian_login():
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Atlassian sign-in is not implemented yet (Phase 5).",
    )
