from fastapi import APIRouter, FastAPI  # type: ignore[import-not-found]

router = APIRouter()
FastAPI.include_router(router)


@router.get("/items")  # type: ignore[untyped-decorator]
def view() -> list[str]:
    return []
