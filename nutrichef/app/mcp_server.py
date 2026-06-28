import sys
import logging
from mcp.server.fastmcp import FastMCP

# Setup error logging so we don't interfere with stdout JSON-RPC
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("nutrichef_mcp")

# Initialize FastMCP Server
mcp = FastMCP("NutriChef Helper Server")

@mcp.tool()
def get_recipe_suggestions(query: str, dietary_restrictions: list[str]) -> list[dict]:
    """
    Get mock recipe suggestions based on search query and dietary restrictions.
    
    Args:
        query: The type of dish or ingredient to search for (e.g., 'pasta', 'salad').
        dietary_restrictions: List of dietary restrictions (e.g., 'vegan', 'gluten-free').
        
    Returns:
        A list of matching recipe dictionaries.
    """
    logger.info(f"get_recipe_suggestions called with query='{query}', restrictions={dietary_restrictions}")
    
    # Mock database of recipes
    database = [
        {
            "recipe_name": "Quinoa Salad Bowl",
            "ingredients": ["quinoa", "cucumber", "tomato", "olive oil", "lemon juice", "avocado"],
            "instructions": ["Rinse and cook quinoa.", "Chop cucumber, tomato, and avocado.", "Toss together with olive oil and lemon juice."],
            "tags": ["vegan", "gluten-free", "dairy-free", "healthy"]
        },
        {
            "recipe_name": "Gluten-Free Tomato Pasta",
            "ingredients": ["gluten-free pasta", "tomato sauce", "garlic", "olive oil", "basil"],
            "instructions": ["Boil gluten-free pasta.", "Sauté garlic in olive oil, add tomato sauce.", "Mix pasta with sauce and garnish with basil."],
            "tags": ["gluten-free", "vegetarian"]
        },
        {
            "recipe_name": "Peanut Butter Oats",
            "ingredients": ["oats", "almond milk", "peanut butter", "banana", "honey"],
            "instructions": ["Cook oats in almond milk.", "Stir in peanut butter and honey.", "Top with sliced banana."],
            "tags": ["vegetarian", "dairy-free"]
        },
        {
            "recipe_name": "Classic Lentil Soup",
            "ingredients": ["lentils", "carrots", "celery", "onion", "vegetable broth", "spinach"],
            "instructions": ["Sauté carrots, celery, and onion.", "Add lentils and vegetable broth; simmer for 25 minutes.", "Stir in spinach before serving."],
            "tags": ["vegan", "gluten-free", "dairy-free"]
        }
    ]
    
    results = []
    query_lower = query.lower()
    for recipe in database:
        # Check query match (recipe name or ingredients)
        matches_query = (
            query_lower in recipe["recipe_name"].lower() or 
            any(query_lower in ing.lower() for ing in recipe["ingredients"])
        )
        
        # Check dietary restrictions match
        matches_restrictions = True
        for restriction in dietary_restrictions:
            if restriction.lower() not in [t.lower() for t in recipe["tags"]]:
                matches_restrictions = False
                break
                
        if matches_query and matches_restrictions:
            results.append(recipe)
            
    # Fallback to general matches if strict search is empty
    if not results:
        results = [r for r in database if matches_restrictions][:2]
        
    return results

@mcp.tool()
def check_allergen_risk(ingredients: list[str], allergens: list[str]) -> dict:
    """
    Check if any ingredients pose a risk for specified allergens.
    
    Args:
        ingredients: List of ingredients to check.
        allergens: List of user allergens (e.g., 'peanuts', 'gluten', 'dairy').
        
    Returns:
        A dictionary indicating if risk is present and listing flagged items.
    """
    logger.info(f"check_allergen_risk called with ingredients={ingredients}, allergens={allergens}")
    
    risk_mapping = {
        "peanuts": ["peanut", "groundnut", "peanut butter"],
        "dairy": ["milk", "cheese", "butter", "cream", "yogurt", "almond milk"], # almond milk is dairy-free, but let's be careful about milk names
        "gluten": ["wheat", "pasta", "flour", "bread", "oats", "barley"],
        "nuts": ["almond", "walnut", "cashew", "peanut", "hazelnut"],
        "soy": ["soy", "tofu", "tempeh", "edamame"]
    }
    
    flagged = []
    has_risk = False
    
    for allergen in allergens:
        allergen_lower = allergen.lower()
        triggers = risk_mapping.get(allergen_lower, [allergen_lower])
        
        for ing in ingredients:
            ing_lower = ing.lower()
            # If ingredient contains any trigger word
            for trigger in triggers:
                if trigger in ing_lower:
                    # Special check: skip if explicitly marked "gluten-free" or "dairy-free"
                    if "free" in ing_lower and ("gluten" in ing_lower or "dairy" in ing_lower):
                        continue
                    flagged.append({
                        "ingredient": ing,
                        "triggered_by_allergen": allergen,
                        "matched_term": trigger
                    })
                    has_risk = True
                    
    return {
        "has_allergen_risk": has_risk,
        "flagged_items": flagged
    }

@mcp.tool()
def parse_pantry_items(available_items: list[str]) -> list[str]:
    """
    Standardize and clean a list of pantry items.
    
    Args:
        available_items: Raw list of available ingredients.
        
    Returns:
        A list of cleaned and standardized items.
    """
    logger.info(f"parse_pantry_items called with available_items={available_items}")
    cleaned = []
    for item in available_items:
        clean = item.strip().lower()
        if clean:
            # Strip measurements or quantities if present
            # e.g., "1 cup of oats" -> "oats"
            for filler in ["1 cup of", "2 cups of", "a pinch of", "tablespoon of", "tbsp of", "tsp of", "grams of", "g of"]:
                if clean.startswith(filler):
                    clean = clean.replace(filler, "").strip()
            cleaned.append(clean)
    return cleaned

if __name__ == "__main__":
    mcp.run(transport="stdio")
