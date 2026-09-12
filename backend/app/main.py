from fastapi import FastAPI

from app.recipe_improvement.http import router as recipe_improvement_router

app = FastAPI(title="AI Service")
app.include_router(recipe_improvement_router)


@app.get("/")
async def hello_world() -> dict[str, str]:
    return {"message": "Hello World"}
