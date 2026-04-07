import aiosqlite
from datetime import date, timedelta
from pydantic import ValidationError

from mealplanner.bot.models import MealEntry, MealPlan, Recipe, ShoppingList, ToolResult

SHOPPING_LIST_SENTINEL = "__shopping_list__:"
from mealplanner.db.database import (
    db_add_recipe,
    db_delete_recipe,
    db_edit_recipe,
    db_get_recipe,
    db_get_meal_plan,
    db_list_recipes,
    db_save_meal_plan,
    db_search_recipes,
)

TOOLS = [
    {
        "name": "save_recipe",
        "description": (
            "Save a finalised recipe to the database. Call this when the user confirms they want to keep a recipe. "
            "Ingredients should be a newline-separated list of plain ingredient names (no quantities, no prep notes). "
            "Instructions should be newline-separated steps."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "ingredients": {
                    "type": "string",
                    "description": "Newline-separated ingredient names, e.g. 'olive oil\\nwhite onions\\ngarlic'",
                },
                "instructions": {
                    "type": "string",
                    "description": "Newline-separated cooking steps",
                },
            },
            "required": ["title", "ingredients", "instructions"],
        },
    },
    {
        "name": "update_recipe",
        "description": (
            "Update an existing saved recipe by ID. Only provide the fields you want to change. "
            "Call this when the user asks to edit or modify a specific recipe."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Recipe ID from list_recipes or save_recipe"},
                "title": {"type": "string"},
                "ingredients": {"type": "string"},
                "instructions": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_recipe",
        "description": (
            "Delete a saved recipe by ID. Confirm with the user before calling this unless the intent is unambiguous."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Recipe ID to delete"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "list_recipes",
        "description": (
            "Return all saved recipes as a list of id and title. Use this to look up IDs before calling "
            "get_recipe, update_recipe, or delete_recipe, or to show the user their collection."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_recipe",
        "description": (
            "Return the full details (title, ingredients, instructions) of a single recipe by ID. "
            "Use this when the user asks about a specific recipe or before suggesting edits."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Recipe ID"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "save_meal_plan",
        "description": (
            "Save a weekly meal plan as a list of recipes (each with their saved recipe ID and title). "
            "Always confirm the week with the user before calling this. "
            "week_of must be the Monday of that week in ISO format (e.g. '2026-04-07'). "
            "Use list_recipes or the ID returned by save_recipe to populate the meals list. "
            "Saving overwrites any existing plan for that week."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "meals": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "description": "Recipe ID"},
                            "title": {"type": "string", "description": "Recipe title"},
                        },
                        "required": ["id", "title"],
                    },
                    "description": "List of meals with their recipe IDs and titles",
                },
                "week_of": {
                    "type": "string",
                    "description": "ISO date of the Monday starting that week, e.g. '2026-04-07'",
                },
            },
            "required": ["meals", "week_of"],
        },
    },
    {
        "name": "search_recipes",
        "description": (
            "Search saved recipes by keyword. Searches both title and ingredients. "
            "Use this when the user asks whether they have a recipe for something, "
            "or wants to find recipes containing a specific ingredient."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to search for in recipe titles and ingredients"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "return_shopping_list",
        "description": (
            "Return the final shopping list to the user. Call this once you have worked out which ingredients "
            "are missing from their existing list. Each item must be a plain ingredient name with no quantities, "
            "no prep notes, and no formatting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Missing ingredients, one plain name per item",
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "get_meal_plan",
        "description": (
            "Retrieve a saved meal plan. Pass week_of (Monday ISO date) to get a specific week, "
            "or omit it to get the most recent plan. Use this when the user asks what's planned "
            "or when generating a shopping list."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "week_of": {
                    "type": "string",
                    "description": "ISO date of the Monday for the desired week, e.g. '2026-04-07' (optional)",
                },
            },
            "required": [],
        },
    },
]


async def execute_tool(name: str, inputs: dict, db: aiosqlite.Connection) -> str:
    try:
        if name == "save_recipe":
            recipe = Recipe(title=inputs["title"], ingredients=inputs["ingredients"], instructions=inputs["instructions"])
            saved = await db_add_recipe(db, recipe.title, recipe.ingredients, recipe.instructions)
            return ToolResult(success=True, message=f"Saved as recipe #{saved.id}", data={"id": saved.id, "title": saved.title}).model_dump_json()

        elif name == "update_recipe":
            found = await db_edit_recipe(
                db,
                id=inputs["id"],
                title=inputs.get("title"),
                ingredients=inputs.get("ingredients"),
                instructions=inputs.get("instructions"),
            )
            if not found:
                return ToolResult(success=False, message=f"No recipe found with id={inputs['id']}").model_dump_json()
            return ToolResult(success=True, message=f"Recipe #{inputs['id']} updated").model_dump_json()

        elif name == "delete_recipe":
            found = await db_delete_recipe(db, inputs["id"])
            if not found:
                return ToolResult(success=False, message=f"No recipe found with id={inputs['id']}").model_dump_json()
            return ToolResult(success=True, message=f"Recipe #{inputs['id']} deleted").model_dump_json()

        elif name == "list_recipes":
            recipes = await db_list_recipes(db)
            if not recipes:
                return ToolResult(success=True, message="No recipes saved yet.").model_dump_json()
            lines = "\n".join(f"{r['id']}: {r['title']}" for r in recipes)
            return ToolResult(success=True, message=lines).model_dump_json()

        elif name == "get_recipe":
            recipe = await db_get_recipe(db, inputs["id"])
            if recipe is None:
                return ToolResult(success=False, message=f"No recipe found with id={inputs['id']}").model_dump_json()
            return ToolResult(
                success=True,
                message=recipe.title,
                data={"title": recipe.title, "ingredients": recipe.ingredients, "instructions": recipe.instructions},
            ).model_dump_json()

        elif name == "search_recipes":
            recipes = await db_search_recipes(db, inputs["query"])
            if not recipes:
                return ToolResult(success=True, message=f"No recipes found matching '{inputs['query']}'.").model_dump_json()
            lines = "\n".join(f"{r['id']}: {r['title']}" for r in recipes)
            return ToolResult(success=True, message=lines).model_dump_json()

        elif name == "save_meal_plan":
            week_of_date = date.fromisoformat(inputs["week_of"])
            if week_of_date.weekday() != 0:  # 0 = Monday
                correct = week_of_date - timedelta(days=week_of_date.weekday())
                return ToolResult(success=False, message=f"week_of must be a Monday. {inputs['week_of']} is a {week_of_date.strftime('%A')}. Use {correct} instead.").model_dump_json()
            entries = [MealEntry(id=m["id"], title=m["title"]) for m in inputs["meals"]]
            plan = MealPlan(meals=entries, week_of=week_of_date)
            await db_save_meal_plan(db, plan.meals, str(plan.week_of))
            return ToolResult(success=True, message=f"Meal plan saved for week of {plan.week_of}.", data={"meals": [m.model_dump() for m in plan.meals], "week_of": str(plan.week_of)}).model_dump_json()

        elif name == "return_shopping_list":
            shopping = ShoppingList(items=inputs["items"])
            return SHOPPING_LIST_SENTINEL + "\n".join(shopping.items)

        elif name == "get_meal_plan":
            week_of = inputs.get("week_of")
            plan = await db_get_meal_plan(db, week_of)
            if plan is None:
                msg = f"No meal plan found for week of {week_of}." if week_of else "No meal plan saved yet."
                return ToolResult(success=True, message=msg).model_dump_json()
            return ToolResult(success=True, message=f"Meal plan for week of {plan.week_of}", data={"meals": [m.model_dump() for m in plan.meals], "week_of": str(plan.week_of)}).model_dump_json()

        else:
            return ToolResult(success=False, message=f"Unknown tool: {name}").model_dump_json()

    except (ValidationError, KeyError) as e:
        return ToolResult(success=False, message=f"Invalid input: {e}").model_dump_json()
    except Exception as e:
        return ToolResult(success=False, message=f"Tool error: {e}").model_dump_json()
