from datetime import date, datetime

from pydantic import BaseModel


class Recipe(BaseModel):
    id: int | None = None
    title: str
    ingredients: str  # newline-separated
    instructions: str  # newline-separated steps
    created_at: datetime | None = None


class MealPlan(BaseModel):
    meals: list[str]  # recipe titles
    week_of: date | None = None


class ToolResult(BaseModel):
    success: bool
    message: str
    data: dict | None = None
