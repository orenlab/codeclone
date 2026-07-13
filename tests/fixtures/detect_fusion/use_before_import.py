from fastapi import APIRouter  # type: ignore[import-not-found]

router = APIRouter()
FastAPI.include_router(router)  # noqa: F821 - intentional use before import

from fastapi import FastAPI  # noqa: E402, F401 - intentional late import


@router.get("/items")  # type: ignore[untyped-decorator]
def view() -> list[str]:
    return []
