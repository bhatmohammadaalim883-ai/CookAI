
const imageInput = document.getElementById("imageInput");
const uploadBox = document.getElementById("uploadBox");
const previewContainer = document.getElementById("previewContainer");
const scanButton = document.getElementById("scanButton");
const loading = document.getElementById("loading");
const errorMessage = document.getElementById("errorMessage");
const results = document.getElementById("results");
const ingredientList = document.getElementById("ingredientList");
const recipeContainer = document.getElementById("recipeContainer");

const manualIngredientInput = document.getElementById("manualIngredientInput");
const manualIngredient = document.getElementById("manualIngredient");
const addIngredientButton = document.getElementById("addIngredientButton");
const findRecipesButton = document.getElementById("findRecipesButton");
const manualFindRecipesButton = document.getElementById("manualFindRecipesButton");

let selectedFiles = [];
let detectedIngredients = [];

const MAX_FILES = 5;
const MAX_TOTAL_SIZE = 15 * 1024 * 1024;
const MAX_INGREDIENTS = 50;

// -----------------------------
// ERROR HANDLING
// -----------------------------

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.remove("hidden");
}

function clearError() {
    errorMessage.textContent = "";
    errorMessage.classList.add("hidden");
}

// -----------------------------
// INGREDIENT HELPERS
// -----------------------------

function cleanIngredient(value) {
    return value.trim().toLowerCase().replace(/\s+/g, " ");
}

function getManualIngredients() {
    return manualIngredientInput.value
        .split(/[,\n]+/)
        .map(cleanIngredient)
        .filter(Boolean);
}

function combineIngredients(first, second) {
    const combined = [];
    const seen = new Set();

    [...first, ...second].forEach(item => {
        const ingredient = cleanIngredient(item);

        if (!ingredient || ingredient.length > 60) {
            return;
        }

        if (!seen.has(ingredient)) {
            seen.add(ingredient);
            combined.push(ingredient);
        }
    });

    return combined.sort();
}

function validateIngredients(ingredients) {
    if (!ingredients.length) {
        showError("Please enter or identify at least one ingredient.");
        return false;
    }

    if (ingredients.length > MAX_INGREDIENTS) {
        showError("You can use a maximum of 50 ingredients.");
        return false;
    }

    if (ingredients.some(item => item.length > 60)) {
        showError("An ingredient name is too long. Maximum 60 characters.");
        return false;
    }

    return true;
}

// -----------------------------
// IMAGE PREVIEWS
// -----------------------------

function renderPreviews() {
    previewContainer.querySelectorAll("img").forEach(image => {
        if (image.src.startsWith("blob:")) {
            URL.revokeObjectURL(image.src);
        }
    });

    previewContainer.replaceChildren();

    selectedFiles.forEach((file, index) => {
        const wrapper = document.createElement("div");
        wrapper.className = "preview-item";

        const image = document.createElement("img");
        image.alt = "Selected ingredient photograph";
        image.src = URL.createObjectURL(file);

        const removeButton = document.createElement("button");
        removeButton.className = "remove-image";
        removeButton.type = "button";
        removeButton.textContent = "×";
        removeButton.setAttribute("aria-label", "Remove image");

        removeButton.addEventListener("click", () => {
            selectedFiles.splice(index, 1);
            renderPreviews();
        });

        wrapper.append(image, removeButton);
        previewContainer.appendChild(wrapper);
    });

    scanButton.disabled = selectedFiles.length === 0;
}

function addFiles(files) {
    clearError();

    const newFiles = Array.from(files);

    if (selectedFiles.length + newFiles.length > MAX_FILES) {
        showError("You can upload a maximum of 5 images.");
        return;
    }

    const combinedSize = [...selectedFiles, ...newFiles]
        .reduce((total, file) => total + file.size, 0);

    if (combinedSize > MAX_TOTAL_SIZE) {
        showError("Your images must be smaller than 15 MB in total.");
        return;
    }

    for (const file of newFiles) {
        if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
            showError("Please select JPG, PNG or WEBP images only.");
            return;
        }
    }

    selectedFiles.push(...newFiles);
    renderPreviews();
}

imageInput.addEventListener("change", event => {
    addFiles(event.target.files);
    imageInput.value = "";
});

["dragenter", "dragover"].forEach(eventName => {
    uploadBox.addEventListener(eventName, event => {
        event.preventDefault();
        uploadBox.classList.add("drag-active");
    });
});

["dragleave", "drop"].forEach(eventName => {
    uploadBox.addEventListener(eventName, event => {
        event.preventDefault();
        uploadBox.classList.remove("drag-active");
    });
});

uploadBox.addEventListener("drop", event => {
    addFiles(event.dataTransfer.files);
});

// -----------------------------
// RENDER INGREDIENTS
// -----------------------------

function renderIngredients() {
    ingredientList.replaceChildren();

    detectedIngredients.forEach((ingredient, index) => {
        const chip = document.createElement("span");
        chip.className = "ingredient-chip";

        const name = document.createElement("span");
        name.textContent = ingredient;

        const remove = document.createElement("button");
        remove.type = "button";
        remove.textContent = "×";
        remove.setAttribute("aria-label", `Remove ${ingredient}`);

        remove.addEventListener("click", () => {
            detectedIngredients.splice(index, 1);
            renderIngredients();
            clearError();
        });

        chip.append(name, remove);
        ingredientList.appendChild(chip);
    });
}

// -----------------------------
// SHOW INGREDIENT RESULTS
// -----------------------------

function showIngredientResults() {
    results.classList.remove("hidden");

    const manualFindArea = document.querySelector(".manual-find-area");

    if (manualFindArea) {
        manualFindArea.classList.add("hidden");
    }

    renderIngredients();

    results.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}

// -----------------------------
// PHOTO SCANNING
// -----------------------------

scanButton.addEventListener("click", async () => {
    if (!selectedFiles.length) {
        return;
    }

    clearError();
    results.classList.add("hidden");
    recipeContainer.replaceChildren();

    scanButton.disabled = true;
    manualFindRecipesButton.disabled = true;
    loading.classList.remove("hidden");

    const formData = new FormData();

    selectedFiles.forEach(file => {
        formData.append("images", file);
    });

    try {
        const response = await fetch("/api/scan", {
            method: "POST",
            body: formData
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Something went wrong.");
        }

        // Combine AI-detected ingredients with manually typed ingredients.
        const typedIngredients = getManualIngredients();

        detectedIngredients = combineIngredients(
            data.ingredients || [],
            typedIngredients
        );

        if (!validateIngredients(detectedIngredients)) {
            return;
        }

        showIngredientResults();

    } catch (error) {
        showError(error.message);
    } finally {
        loading.classList.add("hidden");
        scanButton.disabled = selectedFiles.length === 0;
        manualFindRecipesButton.disabled = false;
    }
});

// -----------------------------
// ADD INDIVIDUAL INGREDIENT
// -----------------------------

function addSingleIngredient() {
    const ingredient = cleanIngredient(manualIngredient.value);

    if (!ingredient) {
        return;
    }

    if (ingredient.length > 60) {
        showError("Ingredient name is too long. Maximum 60 characters.");
        return;
    }

    if (detectedIngredients.length >= MAX_INGREDIENTS &&
        !detectedIngredients.includes(ingredient)) {
        showError("You can use a maximum of 50 ingredients.");
        return;
    }

    detectedIngredients = combineIngredients(
        detectedIngredients,
        [ingredient]
    );

    renderIngredients();

    manualIngredient.value = "";
    clearError();
}

addIngredientButton.addEventListener("click", addSingleIngredient);

manualIngredient.addEventListener("keydown", event => {
    if (event.key === "Enter") {
        event.preventDefault();
        addSingleIngredient();
    }
});

// -----------------------------
// MANUAL-ONLY INGREDIENT ENTRY
// -----------------------------

manualFindRecipesButton.addEventListener("click", () => {
    clearError();

    const typedIngredients = getManualIngredients();

    detectedIngredients = combineIngredients(
        detectedIngredients,
        typedIngredients
    );

    if (!validateIngredients(detectedIngredients)) {
        return;
    }

    recipeContainer.replaceChildren();

    showIngredientResults();
});

// -----------------------------
// RECIPE DISCOVERY
// -----------------------------

async function discoverRecipes() {
    clearError();
    recipeContainer.replaceChildren();

    if (!validateIngredients(detectedIngredients)) {
        return;
    }

    const button = findRecipesButton;

    button.disabled = true;
    button.textContent = "Finding recipes...";

    try {
        const response = await fetch("/api/recipes", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                ingredients: detectedIngredients
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || "Unable to find recipes.");
        }

        renderRecipes(data.recipes || []);

    } catch (error) {
        showError(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "Discover My Recipes →";
    }
}

findRecipesButton.addEventListener("click", discoverRecipes);

// -----------------------------
// RENDER RECIPES
// -----------------------------

function renderRecipes(recipes) {
    recipeContainer.replaceChildren();

    if (!recipes.length) {
        const message = document.createElement("p");

        message.textContent =
            "No matching recipes found. Try adding more ingredients.";

        recipeContainer.appendChild(message);
        return;
    }

    recipes.forEach(recipe => {
        const card = document.createElement("article");
        card.className = "recipe-card";

        const title = document.createElement("h3");
        title.textContent = "🍽️ " + recipe.name;

        const cuisine = document.createElement("p");
        cuisine.textContent = "Cuisine: " + recipe.cuisine;

        const time = document.createElement("p");
        time.textContent = "Preparation time: " + recipe.time;

        const match = document.createElement("p");
        match.className = "match";
        match.textContent =
            recipe.match_percentage + "% ingredient match";

        const matched = document.createElement("p");
        matched.textContent =
            "Available: " + recipe.matched_ingredients.join(", ");

        const missing = document.createElement("p");
        missing.textContent = recipe.missing_ingredients.length
            ? "Still needed: " + recipe.missing_ingredients.join(", ")
            : "You have all listed ingredients!";

        const details = document.createElement("details");

        const summary = document.createElement("summary");
        summary.textContent = "View cooking instructions";

        const instructions = document.createElement("ol");

        (recipe.instructions || []).forEach(step => {
            const item = document.createElement("li");
            item.textContent = step;
            instructions.appendChild(item);
        });

        details.append(summary, instructions);

        card.append(
            title,
            cuisine,
            time,
            match,
            matched,
            missing,
            details
        );

        recipeContainer.appendChild(card);
    });

    recipeContainer.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}
