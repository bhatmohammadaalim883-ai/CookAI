
import os
import json
import time
from io import BytesIO

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError

from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    logout_user,
    login_required,
    current_user
)
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)

# -----------------------------
# APP CONFIGURATION
# -----------------------------

SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY is missing from environment variables.")

app.config["SECRET_KEY"] = SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

database_url = os.getenv("DATABASE_URL", "sqlite:///cookai.db")

if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


# -----------------------------
# USER DATABASE MODEL
# -----------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()


# -----------------------------
# GEMINI CONFIGURATION
# -----------------------------

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

client = genai.Client(api_key=API_KEY) if API_KEY else None

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}

MINIMUM_LOCAL_RECIPES = 5
AI_RECIPE_COUNT = 5
MAX_TOTAL_RECIPES = 10

VALID_DIFFICULTIES = {"Easy", "Medium", "Hard"}


class GeminiTemporaryError(Exception):
    pass


# -----------------------------
# INGREDIENT NORMALIZATION
# -----------------------------

INGREDIENT_ALIASES = {
    "red chilli powder": "chili powder",
    "red chili powder": "chili powder",
    "chilli powder": "chili powder",
    "chile powder": "chili powder",
    "green chilli": "green chili",
    "green chillies": "green chili",
    "green chilies": "green chili",
    "capsicum": "bell pepper",
    "scallion": "spring onion",
    "scallions": "spring onion",
    "aubergine": "eggplant",
    "courgette": "zucchini",
    "coriander leaves": "cilantro",
    "fresh coriander": "cilantro",
    "ground beef": "beef",
    "minced beef": "beef",
    "ground lamb": "lamb",
    "minced lamb": "lamb",
    "prawns": "shrimp",
    "prawn": "shrimp",
    "chicken meat": "chicken",
    "fish fillet": "fish",
    "fish fillets": "fish"
}


def normalize_ingredient(ingredient):

    if not isinstance(ingredient, str):
        return ""

    ingredient = ingredient.strip().lower()
    ingredient = " ".join(ingredient.split())

    return INGREDIENT_ALIASES.get(ingredient, ingredient)


def clean_ingredients(ingredients):

    cleaned = set()

    if not isinstance(ingredients, list):
        return []

    for item in ingredients:
        normalized = normalize_ingredient(item)

        if normalized:
            cleaned.add(normalized)

    return sorted(cleaned)


# -----------------------------
# RECIPE DETAIL VALIDATION
# -----------------------------

def clean_quantity_details(quantity_details, recipe_ingredients):

    if not isinstance(quantity_details, list):
        return []

    valid_ingredients = set(recipe_ingredients)
    cleaned = []
    seen = set()

    for item in quantity_details:

        if not isinstance(item, dict):
            continue

        name = normalize_ingredient(item.get("name", ""))
        quantity = item.get("quantity", "")

        if not name or name not in valid_ingredients:
            continue

        if not isinstance(quantity, str):
            continue

        quantity = quantity.strip()

        if not quantity or len(quantity) > 100:
            continue

        if name in seen:
            continue

        cleaned.append({
            "name": name,
            "quantity": quantity
        })

        seen.add(name)

    return cleaned


def clean_difficulty(value):

    if not isinstance(value, str):
        return "Not specified"

    value = value.strip().capitalize()

    if value not in VALID_DIFFICULTIES:
        return "Not specified"

    return value


def clean_instructions(instructions):

    if not isinstance(instructions, list):
        return []

    cleaned = []

    for step in instructions:

        if isinstance(step, str):
            step = step.strip()

            if step and len(step) <= 1500:
                cleaned.append(step)

    return cleaned[:30]


# -----------------------------
# AUTHENTICATION
# -----------------------------

@app.route("/signup", methods=["GET", "POST"])
def signup():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("Please complete all fields.", "error")
            return redirect(url_for("signup"))

        if len(username) < 3 or len(username) > 50:
            flash("Username must be between 3 and 50 characters.", "error")
            return redirect(url_for("signup"))

        if len(password) < 8:
            flash("Password must contain at least 8 characters.", "error")
            return redirect(url_for("signup"))

        if "@" not in email or "." not in email:
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("signup"))

        existing_user = User.query.filter(
            (User.username == username) | (User.email == email)
        ).first()

        if existing_user:
            flash("That username or email is already registered.", "error")
            return redirect(url_for("signup"))

        user = User(username=username, email=email)
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        login_user(user)

        flash("Your CookAI account has been created!", "success")
        return redirect(url_for("home"))

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():

    if current_user.is_authenticated:
        return redirect(url_for("home"))

    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            login_user(user)
            flash("You are now logged in!", "success")
            return redirect(url_for("home"))

        flash("Incorrect email or password.", "error")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
@login_required
def logout():

    logout_user()
    flash("You have been logged out.", "success")

    return redirect(url_for("home"))


# -----------------------------
# API LOGIN PROTECTION
# -----------------------------

@login_manager.unauthorized_handler
def unauthorized():

    if request.path.startswith("/api/"):
        return jsonify({
            "success": False,
            "error": "Please sign up or log in to use CookAI."
        }), 401

    return redirect(url_for("login"))


# -----------------------------
# HOME PAGE
# -----------------------------

@app.route("/")
def home():
    return render_template("index.html")


# -----------------------------
# RECIPE DATABASE
# -----------------------------

def load_recipes():

    try:

        with open("recipes.json", "r", encoding="utf-8") as file:
            recipes = json.load(file)

        if not isinstance(recipes, list):
            app.logger.error("recipes.json must contain a JSON list.")
            return []

        return recipes

    except (FileNotFoundError, json.JSONDecodeError):

        app.logger.exception("Could not load recipes.json")
        return []


# -----------------------------
# RECIPE MATCHING
# -----------------------------

def prepare_recipe(recipe, available, source="database"):

    recipe_ingredients = clean_ingredients(
        recipe.get("ingredients", [])
    )

    if not recipe_ingredients:
        return None

    matched = sorted(set(recipe_ingredients) & set(available))
    missing = sorted(set(recipe_ingredients) - set(available))

    if not matched:
        return None

    percentage = round(
        len(matched) / len(recipe_ingredients) * 100
    )

    quantity_details = clean_quantity_details(
        recipe.get("ingredient_quantities", []),
        recipe_ingredients
    )

    difficulty = clean_difficulty(
        recipe.get("difficulty", "Not specified")
    )

    instructions = clean_instructions(
        recipe.get("instructions", [])
    )

    return {
        **recipe,
        "name": str(recipe.get("name", "Untitled Recipe")),
        "ingredients": recipe_ingredients,
        "ingredient_quantities": quantity_details,
        "difficulty": difficulty,
        "instructions": instructions,
        "matched_ingredients": matched,
        "missing_ingredients": missing,
        "match_percentage": percentage,
        "matched_count": len(matched),
        "source": source
    }


def recommend_local_recipes(ingredients):

    available = set(clean_ingredients(ingredients))
    recipes = load_recipes()

    recommendations = []

    for recipe in recipes:

        if not isinstance(recipe, dict):
            continue

        prepared = prepare_recipe(recipe, available)

        if prepared:
            recommendations.append(prepared)

    recommendations.sort(
        key=lambda recipe: (
            recipe["match_percentage"],
            recipe["matched_count"],
            -len(recipe["missing_ingredients"])
        ),
        reverse=True
    )

    return recommendations


# -----------------------------
# GEMINI ERROR HANDLING
# -----------------------------

def get_error_status(error):

    status = getattr(error, "code", None)

    if not isinstance(status, int):
        status = getattr(error, "status_code", None)

    if isinstance(status, int):
        return status

    error_text = str(error)

    for code in (429, 500, 502, 503, 504):

        if str(code) in error_text:
            return code

    return None


def call_gemini(prompt, image_parts=None):

    if client is None:
        raise RuntimeError("Gemini API key is not configured.")

    contents = [prompt]

    if image_parts:
        contents.extend(image_parts)

    for attempt in range(3):

        try:

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            if not response.text:
                raise ValueError("Gemini returned an empty response.")

            return response.text

        except ValueError:
            raise

        except Exception as error:

            status = get_error_status(error)

            if status not in {429, 500, 502, 503, 504}:
                raise

            if attempt == 2:

                app.logger.error(
                    "Gemini unavailable after 3 attempts: %s",
                    error
                )

                raise GeminiTemporaryError(
                    "Gemini AI is temporarily busy. Please try again later."
                ) from error

            wait_time = 2 ** (attempt + 1)

            app.logger.warning(
                "Gemini error %s. Retrying in %s seconds.",
                status,
                wait_time
            )

            time.sleep(wait_time)

    raise GeminiTemporaryError(
        "Gemini AI is temporarily unavailable."
    )


# -----------------------------
# AI RECIPE GENERATION
# -----------------------------

def generate_ai_recipes(ingredients):

    if client is None:
        app.logger.warning("AI recipe generation skipped: API key missing.")
        return []

    available = clean_ingredients(ingredients)

    if not available:
        return []

    prompt = f"""
You are CookAI, an expert cooking assistant.

The user has these available ingredients:

{json.dumps(available)}

Generate exactly {AI_RECIPE_COUNT} different practical recipes.

IMPORTANT RULES:

1. Use the user's available ingredients as the main ingredients.
2. Recipes can include vegetables, chicken, meat, fish, eggs,
   rice, pulses, grains, fruits, spices and other foods.
3. Do not assume the user owns ingredients that were not provided.
4. You may include a small number of additional ingredients
   when necessary to make a realistic recipe.
5. Clearly list additional ingredients so CookAI can identify
   what the user is missing.
6. Prefer recipes that can be made with the available ingredients.
7. Include different cooking styles and cuisines when appropriate.
8. Do not create duplicate recipes.
9. Do not invent ingredients that are not real food ingredients.
10. Include clear, practical, numbered cooking instructions.
11. Include sensible quantities for EVERY ingredient.
12. Do not mark an ingredient as available unless it appears
    in the user's ingredient list.
13. Do not include optional ingredients in the required ingredient list.
14. Give appropriate food-safety instructions for meat, poultry,
    fish and eggs.
15. Difficulty must be Easy, Medium or Hard.
16. Difficulty should reflect the actual cooking skill required.
17. Quantities must be realistic and suitable for the recipe.
18. Do not put quantities inside the ingredients list.
19. Include a separate quantity object for each ingredient.
20. Do not omit ingredients from ingredient_quantities.

Return valid JSON only, using this exact structure:

{{
  "recipes": [
    {{
      "name": "Recipe name",
      "ingredients": [
        "potato",
        "onion",
        "oil"
      ],
      "ingredient_quantities": [
        {{
          "name": "potato",
          "quantity": "2 medium"
        }},
        {{
          "name": "onion",
          "quantity": "1 medium"
        }},
        {{
          "name": "oil",
          "quantity": "2 tablespoons"
        }}
      ],
      "difficulty": "Easy",
      "cuisine": "Indian",
      "time": "30 minutes",
      "instructions": [
        "First cooking step.",
        "Second cooking step.",
        "Final cooking step."
      ]
    }}
  ]
}}

The ingredients field must contain simple ingredient names only.

The ingredient_quantities field must contain objects with
"name" and "quantity" properties.

The difficulty field must be exactly Easy, Medium or Hard.

The instructions field must contain a list of clear,
practical cooking steps in the correct order.
"""

    try:

        response_text = call_gemini(prompt)
        result = json.loads(response_text)

        if isinstance(result, list):
            generated = result

        elif isinstance(result, dict):
            generated = result.get("recipes", [])

        else:
            return []

        if not isinstance(generated, list):
            return []

        return generated[:AI_RECIPE_COUNT]

    except GeminiTemporaryError:
        raise

    except Exception:

        app.logger.exception("AI recipe generation failed")
        return []


# -----------------------------
# HYBRID RECIPE ENGINE
# -----------------------------

def recommend_recipes(ingredients):

    available = clean_ingredients(ingredients)

    if not available:
        return []

    # First search the saved recipe database.
    local_recipes = recommend_local_recipes(available)

    # Generate additional recipes only when the database
    # does not provide enough recommendations.
    if len(local_recipes) >= MINIMUM_LOCAL_RECIPES:
        return local_recipes[:MAX_TOTAL_RECIPES]

    try:

        ai_recipes = generate_ai_recipes(available)

    except GeminiTemporaryError:

        app.logger.warning(
            "AI recipe fallback unavailable. Returning saved recipes."
        )

        return local_recipes[:MAX_TOTAL_RECIPES]

    combined = list(local_recipes)

    existing_names = {
        recipe.get("name", "").strip().lower()
        for recipe in local_recipes
    }

    for recipe in ai_recipes:

        if not isinstance(recipe, dict):
            continue

        name = recipe.get("name", "")

        if not isinstance(name, str):
            continue

        name = name.strip()

        if not name or name.lower() in existing_names:
            continue

        ingredients_list = recipe.get("ingredients", [])

        if not isinstance(ingredients_list, list):
            continue

        recipe_ingredients = clean_ingredients(ingredients_list)

        if not recipe_ingredients:
            continue

        instructions = clean_instructions(
            recipe.get("instructions", [])
        )

        if not instructions:
            continue

        # Prepare validated recipe data.
        recipe["name"] = name
        recipe["ingredients"] = recipe_ingredients

        recipe["ingredient_quantities"] = clean_quantity_details(
            recipe.get("ingredient_quantities", []),
            recipe_ingredients
        )

        recipe["difficulty"] = clean_difficulty(
            recipe.get("difficulty", "Not specified")
        )

        recipe["cuisine"] = str(
            recipe.get("cuisine", "International")
        )[:100]

        recipe["time"] = str(
            recipe.get("time", "Not specified")
        )[:100]

        recipe["instructions"] = instructions

        prepared = prepare_recipe(
            recipe,
            set(available),
            source="AI generated"
        )

        if not prepared:
            continue

        combined.append(prepared)
        existing_names.add(name.lower())

        if len(combined) >= MAX_TOTAL_RECIPES:
            break

    combined.sort(
        key=lambda recipe: (
            recipe["match_percentage"],
            recipe["matched_count"],
            -len(recipe["missing_ingredients"])
        ),
        reverse=True
    )

    return combined[:MAX_TOTAL_RECIPES]


# -----------------------------
# IMAGE INGREDIENT RECOGNITION
# -----------------------------

def detect_ingredients(image_file):

    if client is None:
        raise RuntimeError("Gemini API key is not configured.")

    image_bytes = image_file.read()

    if not image_bytes:
        raise ValueError("The uploaded image is empty.")

    try:

        with Image.open(BytesIO(image_bytes)) as image:
            image.verify()

        with Image.open(BytesIO(image_bytes)) as image:

            image = image.convert("RGB")
            image.thumbnail((1200, 1200))

            output = BytesIO()
            image.save(output, format="JPEG", quality=85)

            processed_image = output.getvalue()

    except (UnidentifiedImageError, OSError):
        raise ValueError("Please upload a valid image.")

    prompt = """
Identify the visible food ingredients in this photograph.

Only identify ingredients that are clearly visible.
Do not guess hidden ingredients or complete dishes.

Identify actual ingredients as specifically as possible.
Distinguish chicken from other meats.

Use simple English ingredient names.
Keep spices separate from vegetables and proteins.

Return valid JSON only:

{
  "ingredients": ["chicken", "tomato", "red chili powder"]
}
"""

    image_part = types.Part.from_bytes(
        data=processed_image,
        mime_type="image/jpeg"
    )

    response_text = call_gemini(
        prompt,
        image_parts=[image_part]
    )

    try:

        result = json.loads(response_text)
        ingredients = result.get("ingredients", [])

        if not isinstance(ingredients, list):
            raise ValueError("Invalid AI response.")

        return clean_ingredients(ingredients)

    except (json.JSONDecodeError, AttributeError, TypeError):
        raise ValueError("The AI returned an invalid ingredient list.")


# -----------------------------
# SCAN API — LOGIN REQUIRED
# -----------------------------

@app.route("/api/scan", methods=["POST"])
@login_required
def scan():

    if "images" not in request.files:

        return jsonify({
            "success": False,
            "error": "Please upload ingredient photographs."
        }), 400

    files = request.files.getlist("images")

    if not files or len(files) > 5:

        return jsonify({
            "success": False,
            "error": "Upload between 1 and 5 images."
        }), 400

    detected = set()

    try:

        for image_file in files:

            if not image_file.filename:
                continue

            extension = image_file.filename.rsplit(".", 1)[-1].lower()

            if extension not in ALLOWED_EXTENSIONS:

                return jsonify({
                    "success": False,
                    "error": "Use JPG, JPEG, PNG or WEBP images."
                }), 400

            detected.update(detect_ingredients(image_file))

        if not detected:

            return jsonify({
                "success": False,
                "error": "No ingredients were identified."
            }), 422

        return jsonify({
            "success": True,
            "ingredients": sorted(detected),
            "recipes": [],
            "message": "Ingredients identified successfully!"
        })

    except GeminiTemporaryError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 503

    except ValueError as error:

        return jsonify({
            "success": False,
            "error": str(error)
        }), 400

    except Exception:

        app.logger.exception("CookAI scanning failed")

        return jsonify({
            "success": False,
            "error": "AI scanning failed. Please try again."
        }), 500


# -----------------------------
# RECIPES API — LOGIN REQUIRED
# -----------------------------

@app.route("/api/recipes", methods=["POST"])
@login_required
def get_recipes():

    data = request.get_json(silent=True) or {}
    ingredients = data.get("ingredients", [])

    if not isinstance(ingredients, list):

        return jsonify({
            "success": False,
            "error": "Invalid ingredient list."
        }), 400

    if len(ingredients) > 50:

        return jsonify({
            "success": False,
            "error": "Too many ingredients."
        }), 400

    if any(
        not isinstance(item, str) or len(item) > 60
        for item in ingredients
    ):

        return jsonify({
            "success": False,
            "error": "One or more ingredients are invalid."
        }), 400

    clean_list = clean_ingredients(ingredients)

    if not clean_list:

        return jsonify({
            "success": False,
            "error": "Please provide at least one ingredient."
        }), 400

    try:

        recipes = recommend_recipes(clean_list)

        return jsonify({
            "success": True,
            "recipes": recipes,
            "message": (
                "Recipes found successfully!"
                if recipes
                else "No recipes could be generated. Please try again."
            )
        })

    except GeminiTemporaryError:

        app.logger.exception("Gemini recipe generation unavailable")

        return jsonify({
            "success": True,
            "recipes": recommend_local_recipes(clean_list),
            "message": "Showing saved recipes. AI generation is temporarily unavailable."
        })

    except Exception:

        app.logger.exception("Recipe recommendation failed")

        return jsonify({
            "success": False,
            "error": "Could not retrieve recipes. Please try again."
        }), 500


# -----------------------------
# FILE SIZE ERROR
# -----------------------------

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({
        "success": False,
        "error": "Total image size must be below 15 MB."
    }), 413


# -----------------------------
# RUN APPLICATION
# -----------------------------

if __name__ == "__main__":
    app.run(debug=False, port=5000)
