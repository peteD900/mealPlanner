import aiosqlite
from datetime import date, timedelta
from pydantic import ValidationError

from mealplanner.bot.models import Ingredient, MealEntry, MealPlan, Recipe, ShoppingList, ToolResult

SHOPPING_LIST_SENTINEL = "__shopping_list__:"
from mealplanner.db.database import (
    db_add_recipe,
    db_delete_recipe,
    db_edit_recipe,
    db_get_recipe,
    db_get_meal_plan,
    db_list_core_recipes,
    db_list_recipes,
    db_save_meal_plan,
    db_search_recipes,
)

TOOLS = [
    {
        "name": "save_recipe",
        "description": (
            "Save a finalised recipe to the database. Call this when the user confirms they want to keep a recipe. "
            "Ingredients is a list of objects with a plain shopping-list-ready 'name' (no quantity, no prep notes) "
            "and an optional free-form 'quantity' string (e.g. '2', '300g', '1 tbsp'). "
            "Instructions is a list of cooking steps, one step per item."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "ingredients": {
                    "type": "array",
                    "description": (
                        "List of ingredients. Each item has a plain 'name' (shopping-list ready, no quantity, "
                        "no prep notes) and optional 'quantity' string."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Plain ingredient name, e.g. 'white onions', 'oats', 'olive oil'",
                            },
                            "quantity": {
                                "type": "string",
                                "description": "Optional quantity with unit, e.g. '2', '300g', '1 tbsp'",
                            },
                        },
                        "required": ["name"],
                    },
                },
                "instructions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Cooking steps, one string per step. No leading numbers — the UI numbers them automatically.",
                },
            },
            "required": ["title", "ingredients", "instructions"],
        },
    },
    {
        "name": "update_recipe",
        "description": (
            "Update an existing saved recipe by ID. Only provide the fields you want to change. "
            "Call this when the user asks to edit or modify a specific recipe. "
            "Pass the exact current title of the recipe as expected_title — the server will refuse the "
            "operation if the id doesn't match that title. "
            "Ingredients (if provided) must be a list of objects with a plain shopping-list-ready 'name' "
            "(no quantity, no prep notes) and optional free-form 'quantity' string. Replaces the full "
            "ingredient list — include every ingredient, not just the ones being changed. "
            "Instructions (if provided) is a list of cooking steps, one step per item, no leading numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Recipe ID from list_recipes or save_recipe"},
                "expected_title": {
                    "type": "string",
                    "description": "The current title of the recipe at this id. Operation is refused on mismatch.",
                },
                "title": {"type": "string"},
                "ingredients": {
                    "type": "array",
                    "description": (
                        "Full replacement ingredient list. Each item has a plain 'name' (shopping-list ready) "
                        "and optional 'quantity' string."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                },
                "instructions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "description": "Cooking steps, one string per step. No leading numbers — the UI numbers them automatically.",
                },
            },
            "required": ["id", "expected_title"],
        },
    },
    {
        "name": "delete_recipe",
        "description": (
            "Delete a saved recipe by ID. Pass the exact current title as expected_title — the server "
            "will refuse the operation if the id doesn't match that title. Confirm with the user before "
            "calling this unless the intent is unambiguous."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Recipe ID to delete"},
                "expected_title": {
                    "type": "string",
                    "description": "The current title of the recipe at this id. Operation is refused on mismatch.",
                },
            },
            "required": ["id", "expected_title"],
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
    {
        "name": "mark_recipe_core",
        "description": (
            "Mark or unmark a recipe as a core recipe (a staple meal the user cooks regularly). "
            "Pass is_core=true to mark it as core, is_core=false to unmark it. "
            "Use list_recipes to look up the recipe ID if you don't already have it. "
            "Pass the exact current title as expected_title — the server will refuse the operation "
            "if the id doesn't match that title."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer", "description": "Recipe ID to update"},
                "expected_title": {
                    "type": "string",
                    "description": "The current title of the recipe at this id. Operation is refused on mismatch.",
                },
                "is_core": {"type": "boolean", "description": "true to mark as core, false to unmark"},
            },
            "required": ["id", "expected_title", "is_core"],
        },
    },
    {
        "name": "list_core_recipes",
        "description": (
            "Return all recipes marked as core (staple meals the user cooks regularly). "
            "Use when the user asks to see their core recipes, or when helping plan meals for a week."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


class _InvalidToolInput(Exception):
    """Raised by input normalisers when the caller passed a malformed shape."""


def _normalise_instructions(raw) -> list[str]:
    """Strip each step, drop blanks, flatten any stray embedded newlines."""
    if not isinstance(raw, list):
        raise _InvalidToolInput("instructions must be a list of steps, one step per item")
    steps = []
    for item in raw:
        if not isinstance(item, str):
            raise _InvalidToolInput("each instruction step must be a string")
        cleaned = item.replace("\n", " ").strip()
        if cleaned:
            steps.append(cleaned)
    return steps


async def _verify_expected_title(db: aiosqlite.Connection, id: int, expected_title: str) -> tuple[bool, str | None, Recipe | None]:
    """Return (ok, error_message, recipe). ok=False with error_message if mismatch or missing."""
    recipe = await db_get_recipe(db, id)
    if recipe is None:
        return False, f"No recipe found with id={id}", None
    if recipe.title.strip().casefold() != expected_title.strip().casefold():
        msg = (
            f"Recipe #{id} is actually '{recipe.title}'. Do not retry on #{id}. "
            f"Call search_recipes('{expected_title}') to find the right id."
        )
        return False, msg, recipe
    return True, None, recipe


async def execute_tool(name: str, inputs: dict, db: aiosqlite.Connection) -> str:
    try:
        if name == "save_recipe":
            ingredients = [Ingredient(**i) for i in inputs["ingredients"]]
            steps = _normalise_instructions(inputs["instructions"])
            if not steps:
                return ToolResult(success=False, message="instructions must contain at least one non-empty step").model_dump_json()
            recipe = Recipe(title=inputs["title"], ingredients=ingredients, instructions="\n".join(steps))
            saved = await db_add_recipe(db, recipe.title, recipe.ingredients, recipe.instructions)
            return ToolResult(success=True, message=f"Saved as recipe #{saved.id}", data={"id": saved.id, "title": saved.title}).model_dump_json()

        elif name == "update_recipe":
            ok, err, recipe = await _verify_expected_title(db, inputs["id"], inputs["expected_title"])
            if not ok:
                return ToolResult(success=False, message=err).model_dump_json()
            raw_ingredients = inputs.get("ingredients")
            ingredients = [Ingredient(**i) for i in raw_ingredients] if raw_ingredients is not None else None
            instructions_str = None
            if "instructions" in inputs:
                steps = _normalise_instructions(inputs["instructions"])
                if not steps:
                    return ToolResult(success=False, message="instructions must contain at least one non-empty step").model_dump_json()
                instructions_str = "\n".join(steps)
            new_title = inputs.get("title")
            found = await db_edit_recipe(
                db,
                id=inputs["id"],
                title=new_title,
                ingredients=ingredients,
                instructions=instructions_str,
            )
            if not found:
                return ToolResult(success=False, message=f"No recipe found with id={inputs['id']}").model_dump_json()
            display_title = new_title if new_title is not None else recipe.title
            return ToolResult(success=True, message=f"Recipe #{inputs['id']} '{display_title}' updated").model_dump_json()

        elif name == "delete_recipe":
            ok, err, recipe = await _verify_expected_title(db, inputs["id"], inputs["expected_title"])
            if not ok:
                return ToolResult(success=False, message=err).model_dump_json()
            found = await db_delete_recipe(db, inputs["id"])
            if not found:
                return ToolResult(success=False, message=f"No recipe found with id={inputs['id']}").model_dump_json()
            return ToolResult(success=True, message=f"Recipe #{inputs['id']} '{recipe.title}' deleted").model_dump_json()

        elif name == "list_recipes":
            recipes = await db_list_recipes(db)
            if not recipes:
                return ToolResult(success=True, message="No recipes saved yet.").model_dump_json()
            lines = "\n".join(f"{r['id']}: {r['title']}{' [CORE]' if r['is_core'] else ''}" for r in recipes)
            return ToolResult(success=True, message=lines).model_dump_json()

        elif name == "get_recipe":
            recipe = await db_get_recipe(db, inputs["id"])
            if recipe is None:
                return ToolResult(success=False, message=f"No recipe found with id={inputs['id']}").model_dump_json()
            return ToolResult(
                success=True,
                message=recipe.title,
                data={
                    "title": recipe.title,
                    "ingredients": [i.model_dump() for i in recipe.ingredients],
                    "instructions": recipe.instructions,
                    "is_core": recipe.is_core,
                },
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

        elif name == "mark_recipe_core":
            ok, err, recipe = await _verify_expected_title(db, inputs["id"], inputs["expected_title"])
            if not ok:
                return ToolResult(success=False, message=err).model_dump_json()
            found = await db_edit_recipe(db, id=inputs["id"], is_core=inputs["is_core"])
            if not found:
                return ToolResult(success=False, message=f"No recipe found with id={inputs['id']}").model_dump_json()
            status = "marked as core" if inputs["is_core"] else "unmarked as core"
            return ToolResult(success=True, message=f"Recipe #{inputs['id']} '{recipe.title}' {status}").model_dump_json()

        elif name == "list_core_recipes":
            recipes = await db_list_core_recipes(db)
            if not recipes:
                return ToolResult(success=True, message="No core recipes saved yet.").model_dump_json()
            lines = "\n".join(f"{r['id']}: {r['title']}" for r in recipes)
            return ToolResult(success=True, message=lines).model_dump_json()

        else:
            return ToolResult(success=False, message=f"Unknown tool: {name}").model_dump_json()

    except (ValidationError, KeyError, _InvalidToolInput) as e:
        return ToolResult(success=False, message=f"Invalid input: {e}").model_dump_json()
    except Exception as e:
        return ToolResult(success=False, message=f"Tool error: {e}").model_dump_json()
