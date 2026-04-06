"""
Tests for the tool executor layer. No Claude API calls involved.
"""
import json
import pytest
from mealplanner.bot.tools import execute_tool, SHOPPING_LIST_SENTINEL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def ok(result: str) -> dict:
    data = json.loads(result)
    assert data["success"] is True, f"Expected success, got: {data}"
    return data


def fail(result: str) -> dict:
    data = json.loads(result)
    assert data["success"] is False, f"Expected failure, got: {data}"
    return data


async def save_recipe(db, title="Test Pasta", ingredients="pasta\ngarlic", instructions="cook it"):
    result = ok(await execute_tool("save_recipe", {
        "title": title,
        "ingredients": ingredients,
        "instructions": instructions,
    }, db))
    return result["data"]["id"]


# ---------------------------------------------------------------------------
# save_recipe
# ---------------------------------------------------------------------------

async def test_save_recipe_returns_id(db):
    result = ok(await execute_tool("save_recipe", {
        "title": "Halloumi Wraps",
        "ingredients": "halloumi\npita\ntomatoes",
        "instructions": "grill halloumi\nassemble wrap",
    }, db))
    assert result["data"]["id"] == 1
    assert result["data"]["title"] == "Halloumi Wraps"
    assert "Saved as recipe #1" in result["message"]


async def test_save_recipe_missing_field(db):
    fail(await execute_tool("save_recipe", {"title": "No ingredients"}, db))


# ---------------------------------------------------------------------------
# get_recipe
# ---------------------------------------------------------------------------

async def test_get_recipe(db):
    rid = await save_recipe(db, title="Sweet Potato Salad")
    result = ok(await execute_tool("get_recipe", {"id": rid}, db))
    assert result["data"]["title"] == "Sweet Potato Salad"
    assert "pasta" in result["data"]["ingredients"] or "garlic" in result["data"]["ingredients"]


async def test_get_recipe_not_found(db):
    fail(await execute_tool("get_recipe", {"id": 999}, db))


# ---------------------------------------------------------------------------
# list_recipes
# ---------------------------------------------------------------------------

async def test_list_recipes_empty(db):
    result = ok(await execute_tool("list_recipes", {}, db))
    assert "No recipes" in result["message"]


async def test_list_recipes(db):
    await save_recipe(db, title="Recipe A")
    await save_recipe(db, title="Recipe B")
    result = ok(await execute_tool("list_recipes", {}, db))
    assert "Recipe A" in result["message"]
    assert "Recipe B" in result["message"]


# ---------------------------------------------------------------------------
# update_recipe
# ---------------------------------------------------------------------------

async def test_update_recipe(db):
    rid = await save_recipe(db, title="Original Title")
    ok(await execute_tool("update_recipe", {"id": rid, "title": "Updated Title"}, db))
    result = ok(await execute_tool("get_recipe", {"id": rid}, db))
    assert result["data"]["title"] == "Updated Title"


async def test_update_recipe_not_found(db):
    fail(await execute_tool("update_recipe", {"id": 999, "title": "Ghost"}, db))


# ---------------------------------------------------------------------------
# delete_recipe
# ---------------------------------------------------------------------------

async def test_delete_recipe(db):
    rid = await save_recipe(db)
    ok(await execute_tool("delete_recipe", {"id": rid}, db))
    fail(await execute_tool("get_recipe", {"id": rid}, db))


async def test_delete_recipe_not_found(db):
    fail(await execute_tool("delete_recipe", {"id": 999}, db))


# ---------------------------------------------------------------------------
# search_recipes
# ---------------------------------------------------------------------------

async def test_search_recipes_by_title(db):
    await save_recipe(db, title="Chipotle Lime Chicken")
    await save_recipe(db, title="Halloumi Wraps")
    result = ok(await execute_tool("search_recipes", {"query": "chipotle"}, db))
    assert "Chipotle" in result["message"]
    assert "Halloumi" not in result["message"]


async def test_search_recipes_by_ingredient(db):
    await save_recipe(db, title="Pasta", ingredients="pasta\ngarlic\nolive oil")
    await save_recipe(db, title="Salad", ingredients="lettuce\ntomato\nolive oil")
    result = ok(await execute_tool("search_recipes", {"query": "garlic"}, db))
    assert "Pasta" in result["message"]
    assert "Salad" not in result["message"]


async def test_search_recipes_no_match(db):
    await save_recipe(db, title="Pasta")
    result = ok(await execute_tool("search_recipes", {"query": "xyzzy"}, db))
    assert "No recipes found" in result["message"]


# ---------------------------------------------------------------------------
# save_meal_plan / get_meal_plan
# ---------------------------------------------------------------------------

async def test_save_and_get_meal_plan(db):
    r1 = await save_recipe(db, title="Pasta")
    r2 = await save_recipe(db, title="Salad")
    ok(await execute_tool("save_meal_plan", {
        "meals": [{"id": r1, "title": "Pasta"}, {"id": r2, "title": "Salad"}],
        "week_of": "2026-04-06",
    }, db))
    result = ok(await execute_tool("get_meal_plan", {}, db))
    titles = [m["title"] for m in result["data"]["meals"]]
    assert "Pasta" in titles
    assert "Salad" in titles


async def test_save_meal_plan_rejects_non_monday(db):
    rid = await save_recipe(db)
    result = fail(await execute_tool("save_meal_plan", {
        "meals": [{"id": rid, "title": "Test"}],
        "week_of": "2026-04-09",  # Thursday
    }, db))
    assert "Monday" in result["message"]
    assert "2026-04-06" in result["message"]  # corrected Monday


async def test_save_meal_plan_upserts(db):
    rid = await save_recipe(db, title="Pasta")
    rid2 = await save_recipe(db, title="Salad")
    await execute_tool("save_meal_plan", {
        "meals": [{"id": rid, "title": "Pasta"}],
        "week_of": "2026-04-06",
    }, db)
    # Save again for same week — should overwrite
    ok(await execute_tool("save_meal_plan", {
        "meals": [{"id": rid2, "title": "Salad"}],
        "week_of": "2026-04-06",
    }, db))
    result = ok(await execute_tool("get_meal_plan", {"week_of": "2026-04-06"}, db))
    titles = [m["title"] for m in result["data"]["meals"]]
    assert titles == ["Salad"]


async def test_get_meal_plan_not_found(db):
    result = ok(await execute_tool("get_meal_plan", {}, db))
    assert "No meal plan" in result["message"]


# ---------------------------------------------------------------------------
# return_shopping_list
# ---------------------------------------------------------------------------

async def test_return_shopping_list(db):
    result = await execute_tool("return_shopping_list", {
        "items": ["olive oil", "garlic", "lemon"]
    }, db)
    assert result.startswith(SHOPPING_LIST_SENTINEL)
    items = result[len(SHOPPING_LIST_SENTINEL):].splitlines()
    assert items == ["olive oil", "garlic", "lemon"]


# ---------------------------------------------------------------------------
# Scenario: full recipe → meal plan → shopping list flow
# ---------------------------------------------------------------------------

async def test_full_flow(db):
    """Save two recipes, plan a week, verify meal plan contains correct IDs."""
    r1 = await save_recipe(db, title="Halloumi Wraps", ingredients="halloumi\npita\ntomatoes\nlettuce")
    r2 = await save_recipe(db, title="Chipotle Chicken", ingredients="chicken\nchipotle\nlime\ngarlic")

    ok(await execute_tool("save_meal_plan", {
        "meals": [
            {"id": r1, "title": "Halloumi Wraps"},
            {"id": r2, "title": "Chipotle Chicken"},
        ],
        "week_of": "2026-04-06",
    }, db))

    plan = ok(await execute_tool("get_meal_plan", {}, db))
    ids = [m["id"] for m in plan["data"]["meals"]]
    assert r1 in ids
    assert r2 in ids

    # Fetch ingredients for each meal (as Claude would do for shopping list)
    all_ingredients = []
    for meal in plan["data"]["meals"]:
        recipe = ok(await execute_tool("get_recipe", {"id": meal["id"]}, db))
        all_ingredients.extend(recipe["data"]["ingredients"].splitlines())

    assert "halloumi" in all_ingredients
    assert "chicken" in all_ingredients
