
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
    database_url = database_url.replace(
        "postgres://", "postgresql://", 1
    )

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
    "bell pepper": "bell pepper",
    "capsicum": "bell pepper",
    "spring onion": "spring onion",
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


# Main protein categories.
# A recipe requiring a different protein will not be recommended.

PROTEIN_GROUPS = {
    "chicken": {"chicken"},
    "beef": {"beef"},
    "lamb": {"lamb"},
    "fish": {"fish"},
    "egg": {"egg"},
    "pork": {"pork"},
    "shrimp": {"shrimp"},
    "turkey": {"turkey"},
    "duck": {"duck"}
}

PROTEIN_INGREDIENTS = set().union(*PROTEIN_GROUPS.values())


def get_proteins(ingredients):
    return set(ingredients) & PROTEIN_INGREDIENTS


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

        user = User(
            username=username,
            email=email
        )
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
# SMART RECIPE RECOMMENDATION
# -----------------------------

def recommend_recipes(ingredients):

    recipes = load_recipes()

    available = {
        normalize_ingredient(item)
        for item in ingredients
        if normalize_ingredient(item)
    }

    detected_proteins = get_proteins(available)

    recommendations = []

    for recipe in recipes:

        recipe_ingredients = {
            normalize_ingredient(item)
            for item in recipe.get("ingredients", [])
            if normalize_ingredient(item)
        }

        if not recipe_ingredients:
            continue

        recipe_proteins = get_proteins(recipe_ingredients)

        # If the user has identified a protein, only recommend
        # recipes containing that same protein.
        if detected_proteins:

            if not recipe_proteins:
                continue

            if not recipe_proteins.issubset(detected_proteins):
                continue

        # Do not recommend meat recipes when no matching
        # meat or protein has been identified.
        elif recipe_proteins:
            continue

        matched = sorted(recipe_ingredients & available)
        missing = sorted(recipe_ingredients - available)

        if not matched:
            continue

        # For protein recipes, the protein itself is essential.
        if recipe_proteins and not (recipe_proteins & available):
            continue

        # Prevent recommendations based on just one common
        # ingredient such as tomato or onion.
        if len(matched) < 2 and not recipe_proteins:
            continue

        percentage = round(
            len(matched) / len(recipe_ingredients) * 100
        )

        # Give priority to recipes matching their main protein.
        primary_match = bool(recipe_proteins & available)

        recommendations.append({
            **recipe,
            "matched_ingredients": matched,
            "missing_ingredients": missing,
            "match_percentage": percentage,
            "matched_count": len(matched),
            "primary_match": primary_match
        })

    recommendations.sort(
        key=lambda recipe: (
            recipe["primary_match"],
            recipe["match_percentage"],
            recipe["matched_count"]
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


# -----------------------------
# INGREDIENT RECOGNITION
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

    Identify the actual ingredient as specifically as possible.
    For example, distinguish chicken from other meats.

    Use simple English ingredient names.
    Keep spices separate from vegetables and proteins.

    Return valid JSON only:
    {
      "ingredients": ["chicken", "tomato", "red chili powder"]
    }
    """

    for attempt in range(3):

        try:

            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=[
                    prompt,
                    types.Part.from_bytes(
                        data=processed_image,
                        mime_type="image/jpeg"
                    )
                ],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )

            if not response.text:
                raise ValueError("The AI returned an empty response.")

            result = json.loads(response.text)
            ingredients = result.get("ingredients", [])

            if not isinstance(ingredients, list):
                raise ValueError("Invalid AI response.")

            return sorted({
                normalize_ingredient(item)
                for item in ingredients
                if isinstance(item, str) and item.strip()
            } - {""})

        except ValueError:
            raise

        except Exception as error:

            status = get_error_status(error)
            temporary_errors = {429, 500, 502, 503, 504}

            if status not in temporary_errors:
                raise

            if attempt == 2:

                app.logger.error(
                    "Gemini remained unavailable after 3 attempts: %s",
                    error
                )

                raise GeminiTemporaryError(
                    "Gemini AI is temporarily busy. Please try again later."
                ) from error

            wait_time = 2 ** (attempt + 1)

            app.logger.warning(
                "Gemini temporary error %s. Retrying in %s seconds. Attempt %s/3.",
                status,
                wait_time,
                attempt + 1
            )

            time.sleep(wait_time)

    raise GeminiTemporaryError(
        "Gemini AI is temporarily unavailable. Please try again later."
    )


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

        ingredients = sorted(detected)
        recipes = recommend_recipes(ingredients)

        message = (
            "Ingredients identified successfully!"
            if recipes
            else "Ingredients identified, but no suitable recipes were found."
        )

        return jsonify({
            "success": True,
            "ingredients": ingredients,
            "recipes": recipes,
            "message": message
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

    clean_ingredients = [
        normalize_ingredient(item)
        for item in ingredients
        if isinstance(item, str) and item.strip()
    ]

    recipes = recommend_recipes(clean_ingredients)

    return jsonify({
        "success": True,
        "recipes": recipes,
        "message": (
            "Recipes found successfully!"
            if recipes
            else "No suitable recipes found. Try adding different ingredients."
        )
    })


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
