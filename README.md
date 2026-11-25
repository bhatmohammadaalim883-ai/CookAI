
# CookAI 🍳

### AI-Powered Ingredient Recognition and Recipe Recommendation

CookAI is a web application that analyses uploaded ingredient photographs using Google's Gemini vision model and recommends recipes based on the recognised ingredients.

## Technologies

- HTML
- CSS
- JavaScript
- Python
- Flask
- Google Gemini API
- JSON

## Features

- Multiple image uploads
- AI-powered ingredient recognition
- Manual ingredient correction
- Recipe recommendations
- Missing ingredient information
- Cooking instructions
- Recipe match percentage

## Run locally

1. Install Python.
2. Create a virtual environment.
3. Install dependencies:

   pip install -r requirements.txt

4. Create a private `.env` file containing:

   GEMINI_API_KEY=your_api_key
   GEMINI_MODEL=gemini-3.8-flash

5. Start the application:

   python app.py

6. Open http://127.0.0.1:5000

## Project

Created as a Class 11 Informatics Practices project.
