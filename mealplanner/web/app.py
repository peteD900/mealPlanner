from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from mealplanner.db.database import open_db, db_get_recipe, db_list_recipes

app = FastAPI()
templates = Jinja2Templates(directory="mealplanner/web/templates")


@app.get("/", response_class=HTMLResponse)
async def recipe_list(request: Request):
    async with open_db() as db:
        recipes = await db_list_recipes(db)
    return templates.TemplateResponse(
        "recipe_list.html", {"request": request, "recipes": recipes}
    )


@app.get("/recipe/{recipe_id}", response_class=HTMLResponse)
async def recipe_detail(request: Request, recipe_id: int):
    async with open_db() as db:
        recipe = await db_get_recipe(db, recipe_id)
    if not recipe:
        raise HTTPException(status_code=404, detail="Recipe not found")
    return templates.TemplateResponse(
        "recipe_detail.html", {"request": request, "recipe": recipe}
    )
