from pypdf import PdfReader
import json

def load_linkedin_text():
    """Safely load LinkedIn PDF text without crashing the app."""
    try:
        reader = PdfReader("./data/linkedin.pdf")
        linkedin_text = ""

        for page in reader.pages:
            try:
                text = page.extract_text()  # This is where bbox error happens
                if text:
                    linkedin_text += text
            except Exception as e:
                # Skip problematic pages
                print(f"Warning: Failed to extract page text: {e}")
                continue

        return linkedin_text or "LinkedIn PDF contains unreadable text."

    except FileNotFoundError:
        return "LinkedIn profile not available"

# Lazy load only when needed
linkedin = load_linkedin_text()

# Read other data files
with open("./data/summary.txt", "r", encoding="utf-8") as f:
    summary = f.read()

with open("./data/style.txt", "r", encoding="utf-8") as f:
    style = f.read()

with open("./data/facts.json", "r", encoding="utf-8") as f:
    facts = json.load(f)
