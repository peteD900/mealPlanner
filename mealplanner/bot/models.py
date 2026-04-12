from datetime import date, datetime

from pydantic import BaseModel


class Ingredient(BaseModel):
    name: str  # plain shopping-list-ready name, e.g. "white onions"
    quantity: str | None = None  # optional free-form quantity, e.g. "2", "300g", "1 tbsp"


class Recipe(BaseModel):
    id: int | None = None
    title: str
    ingredients: list[Ingredient]
    instructions: str  # newline-separated steps
    created_at: datetime | None = None
    is_core: bool = False


class MealEntry(BaseModel):
    id: int   # recipe ID
    title: str


class MealPlan(BaseModel):
    meals: list[MealEntry]
    week_of: date  # always a Monday


class ShoppingList(BaseModel):
    items: list[str]  # plain ingredient names, one per item


class ToolResult(BaseModel):
    success: bool
    message: str
    data: dict | None = None
