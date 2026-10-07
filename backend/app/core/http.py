from fastapi import APIRouter


router = APIRouter()


@router.get("/")
async def hello_world() -> dict[str, str]:
    return {"message": "Hello World"}
