import aiosqlite

from db.database import (
    db_add_recipe,
    db_delete_recipe,
    db_edit_recipe,
    db_list_recipes,
)

TOOLS = [
    {
        "name": "add_recipe",
        "description": "Save a new recipe to the database.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "ingredients": {
                    "type": "string",
                    "description": "Newline-separated ingredient list",
                },
                "instructions": {
                    "type": "string",
                    "description": "Step-by-step cooking instructions",
                },
            },
            "required": ["title", "ingredients", "instructions"],
        },
    },
    {
        "name": "edit_recipe",
        "description": "Update an existing recipe by its ID. Only provide fields you want to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "title": {"type": "string"},
                "ingredients": {"type": "string"},
                "instructions": {"type": "string"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "delete_recipe",
        "description": "Delete a recipe by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
            },
            "required": ["id"],
        },
    },
    {
        "name": "list_recipes",
        "description": "Return a list of all saved recipes (id and title only).",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]


async def execute_tool(name: str, inputs: dict, db: aiosqlite.Connection) -> str:
    if name == "add_recipe":
        recipe_id = await db_add_recipe(db, **inputs)
        return f"Recipe saved with id={recipe_id}"
    elif name == "edit_recipe":
        await db_edit_recipe(db, **inputs)
        return "Recipe updated"
    elif name == "delete_recipe":
        await db_delete_recipe(db, inputs["id"])
        return "Recipe deleted"
    elif name == "list_recipes":
        recipes = await db_list_recipes(db)
        if not recipes:
            return "No recipes saved yet."
        return "\n".join(f"{r[0]}: {r[1]}" for r in recipes)
    else:
        return f"Unknown tool: {name}"
