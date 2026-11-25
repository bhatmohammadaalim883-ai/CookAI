
import os
import json
import time
from io import BytesIO

from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
from google import genai
from google.genai import types
from PIL import Image, UnidentifiedImageError

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024

API_KEY = os.getenv("GEMINI_API_KEY")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

client = genai.Client(api_key=API_KEY) if API_KEY else None

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


class GeminiTemporaryError(Exception):
    """Raised when Gemini remains temporarily unavailable."""


def load_recipes():
    try:
        with open("recipes.json", "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def get_error_status(error):
    """Extract an HTTP status code from a Gemini API error."""
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

    Return valid JSON only:
    {
      "ingredients": ["potato", "tomato", "onion"]
    }

    Use simple English ingredient names.
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
                item.strip().lower()
                for item in ingredients
                if isinstance(item, str) and item.strip()
            })

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
                    "Gemini AI is temporarily busy. Please try again in a few minutes."
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


def recommend_recipes(ingredients):
    recipes = load_recipes()
    available = set(ingredients)
    recommendations = []

    for recipe in recipes:
        required = set(recipe.get("ingredients", []))

        if not required:
            continue

        matched = sorted(required & available)
        missing = sorted(required - available)

        if not matched:
            continue

        percentage = round(len(matched) / len(required) * 100)

        recommendations.append({
            **recipe,
            "matched_ingredients": matched,
            "missing_ingredients": missing,
            "match_percentage": percentage
        })

    recommendations.sort(
        key=lambda recipe: recipe["match_percentage"],
        reverse=True
    )

    return recommendations


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/scan", methods=["POST"])
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

        return jsonify({
            "success": True,
            "ingredients": ingredients,
            "recipes": recipes,
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
            "error": "AI scanning failed. Please check the API configuration and try again."
        }), 500


@app.route("/api/recipes", methods=["POST"])
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
        item.strip().lower()
        for item in ingredients
        if isinstance(item, str) and item.strip()
    ]

    recipes = recommend_recipes(clean_ingredients)

    return jsonify({
        "success": True,
        "recipes": recipes
    })


@app.errorhandler(413)
def file_too_large(error):
    return jsonify({
        "success": False,
        "error": "Total image size must be below 15 MB."
    }), 413


if __name__ == "__main__":
    app.run(debug=False, port=5000)
