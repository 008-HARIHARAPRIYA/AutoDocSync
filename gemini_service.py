import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure Gemini API
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

def generate_readme_from_code(code):
    """Generate README using Gemini AI"""
    # Use Gemini 2.5 Flash (correct model name)
    model = genai.GenerativeModel("gemini-2.5-flash")

    prompt = f"""
You are an expert software documentation writer.

**STRICT RULES:**
1. Use ONLY the code provided below
2. Do NOT invent or assume features that aren't in the code
3. Analyze ALL programming languages present (Java, Python, JavaScript, etc.)
4. Write in proper Markdown format
5. Be comprehensive but accurate

**Generate a professional README.md that includes:**
- Project title and description (infer from code)
- Features list (based only on actual code)
- Technology stack (languages, frameworks detected)
- File structure overview
- How to run/compile (based on language detected)
- Code highlights and important components
- Usage examples if applicable

**Code to document:**

{code}

---

Generate the README now:
"""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"  ✗ Gemini API error: {str(e)}")
        return f"# Project Documentation\n\nError generating documentation: {str(e)}"