
const imageInput = document.getElementById("imageInput");
const uploadBox = document.getElementById("uploadBox");
const previewContainer = document.getElementById("previewContainer");
const scanButton = document.getElementById("scanButton");
const loading = document.getElementById("loading");
const errorMessage = document.getElementById("errorMessage");
const results = document.getElementById("results");
const ingredientList = document.getElementById("ingredientList");
const recipeContainer = document.getElementById("recipeContainer");

let selectedFiles = [];
let detectedIngredients = [];

const MAX_FILES = 5;
const MAX_TOTAL_SIZE = 15 * 1024 * 1024;

function showError(message) {
    errorMessage.textContent = message;
    errorMessage.classList.remove("hidden");
}

function clearError() {
    errorMessage.textContent = "";
    errorMessage.classList.add("hidden");
}

function renderPreviews() {
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

    const combinedSize = [
        ...selectedFiles,
        ...newFiles
    ].reduce((total, file) => total + file.size, 0);

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

scanButton.addEventListener("click", async () => {
    if (!selectedFiles.length) return;

    clearError();
    results.classList.add("hidden");
    recipeContainer.replaceChildren();

    scanButton.disabled = true;
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

        detectedIngredients = data.ingredients;
        renderIngredients();

        results.classList.remove("hidden");
        results.scrollIntoView({
            behavior: "smooth",
            block: "start"
        });

    } catch (error) {
        showError(error.message);
    } finally {
        loading.classList.add("hidden");
        scanButton.disabled = selectedFiles.length === 0;
    }
});

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
        });

        chip.append(name, remove);
        ingredientList.appendChild(chip);
    });
}

document.getElementById("addIngredientButton").addEventListener("click", () => {
    const input = document.getElementById("manualIngredient");
    const ingredient = input.value.trim().toLowerCase();

    if (!ingredient) return;

    if (ingredient.length > 40) {
        showError("Ingredient name is too long.");
        return;
    }

    if (!detectedIngredients.includes(ingredient)) {
        detectedIngredients.push(ingredient);
        detectedIngredients.sort();
        renderIngredients();
    }

    input.value = "";
    clearError();
});

document.getElementById("manualIngredient").addEventListener("keydown", event => {
    if (event.key === "Enter") {
        event.preventDefault();
        document.getElementById("addIngredientButton").click();
    }
});

document.getElementById("findRecipesButton").addEventListener("click", async () => {
    recipeContainer.replaceChildren();

    if (!detectedIngredients.length) {
        showError("Please keep at least one ingredient.");
        return;
    }

    const button = document.getElementById("findRecipesButton");
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

        renderRecipes(data.recipes);

    } catch (error) {
        showError(error.message);
    } finally {
        button.disabled = false;
        button.textContent = "Find My Recipes →";
    }
});

function renderRecipes(recipes) {
    recipeContainer.replaceChildren();

    if (!recipes.length) {
        const message = document.createElement("p");
        message.textContent = "No matching recipes found. Try adding more ingredients.";
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
        match.textContent = recipe.match_percentage + "% ingredient match";

        const matched = document.createElement("p");
        matched.textContent = "Available: " + recipe.matched_ingredients.join(", ");

        const missing = document.createElement("p");
        missing.textContent = recipe.missing_ingredients.length
            ? "Still needed: " + recipe.missing_ingredients.join(", ")
            : "You have all listed ingredients!";

        const details = document.createElement("details");
        const summary = document.createElement("summary");
        summary.textContent = "View cooking instructions";

        const instructions = document.createElement("ol");

        recipe.instructions.forEach(step => {
            const item = document.createElement("li");
            item.textContent = step;
            instructions.appendChild(item);
        });

        details.append(summary, instructions);
        card.append(title, cuisine, time, match, matched, missing, details);

        recipeContainer.appendChild(card);
    });

    recipeContainer.scrollIntoView({
        behavior: "smooth",
        block: "start"
    });
}
