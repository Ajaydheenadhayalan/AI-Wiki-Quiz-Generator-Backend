import os
import json
from typing import Any, List, Tuple, Union
from dotenv import load_dotenv
import google.generativeai as genai
from models import QuizOutput

load_dotenv()

API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    raise RuntimeError("Set GEMINI_API_KEY or GOOGLE_API_KEY in backend/.env")

genai.configure(api_key=API_KEY)

PROMPT_TEMPLATE = """You are an expert educational content generator specializing in creating high-quality quizzes from Wikipedia articles.

Your task is to analyze the provided Wikipedia article and generate a comprehensive quiz package.

CRITICAL RULES:
1. Use ONLY facts explicitly stated in the article text - NO external knowledge or assumptions
2. Questions must be directly answerable from the article content
3. All four options must be plausible to avoid obvious answers
4. Explanations should reference specific sections or context from the article
5. Distribute difficulty levels: ~40% easy, ~40% medium, ~20% hard
6. Extract entities that are actually mentioned in the text
7. Return VALID JSON matching the schema EXACTLY (no markdown, no comments, no extra keys)

TASKS:
1. **Summary**: Write a 2-3 sentence concise summary capturing the main topic and key points
2. **Key Entities**: Extract entities that appear prominently in the article:
   - people: Named individuals mentioned
   - organizations: Companies, institutions, groups
   - locations: Cities, countries, regions
3. **Sections**: List 4-6 main section headings or topic areas covered
4. **Quiz**: Generate 5-10 multiple-choice questions:
   - Each question must have EXACTLY 4 options
   - One correct answer that matches one of the options exactly
   - Difficulty: easy (basic facts), medium (requires understanding), hard (detailed knowledge)
   - Explanation: Brief reason citing article section or context
5. **Related Topics**: Suggest 3-5 related Wikipedia topics for further reading

JSON SCHEMA (return ONLY this, nothing else):
{{
  "url": "{url}",
  "title": "{title}",
  "summary": "string (2-3 sentences)",
  "key_entities": {{
    "people": ["string"],
    "organizations": ["string"],
    "locations": ["string"]
  }},
  "sections": ["string"],
  "quiz": [
    {{
      "question": "string",
      "options": ["string", "string", "string", "string"],
      "answer": "string (must match one option exactly)",
      "difficulty": "easy" | "medium" | "hard",
      "explanation": "string (reference article section/context)"
    }}
  ],
  "related_topics": ["string"]
}}

ARTICLE DATA:
URL: {url}
TITLE: {title}

ARTICLE TEXT:
{article_text}

Generate the quiz now. Return ONLY valid JSON, no other text.
"""


def _pick_model() -> str:
    """
    Detect available models on this API key and pick a good one that supports generateContent.
    Preference: gemini-1.5-flash > gemini-1.5-flash-8b > any 'flash' > any generateContent-capable model.
    Allows override with GEMINI_MODEL env if it exists and is supported.
    """
    models = list(genai.list_models())
    gen_models = [m for m in models if "generateContent" in getattr(m, "supported_generation_methods", [])]
    if not gen_models:
        raise RuntimeError("No Gemini models with generateContent are available to this API key.")

    names = [m.name for m in gen_models] 
    simple = [n.split("/")[-1] for n in names]

    desired = os.getenv("GEMINI_MODEL")
    if desired:
        if desired in simple:
            return f"models/{desired}"
        if desired.startswith("models/") and desired.split("/")[-1] in simple:
            return desired
        
    preferences: List[str] = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
    ]

    for p in preferences:
        if p in simple:
            return f"models/{p}"

    for s in simple:
        if "flash" in s:
            return f"models/{s}"
    return names[0]

def _clean_json_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return text
    if text.startswith("```"):
        text = text.strip().strip("`")
        if text.startswith("json"):
            text = text[4:].lstrip()
    if text and not (text.strip().startswith("{") and text.strip().endswith("}")):
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    return text

def _try_once(model_name: str, prompt: str) -> Tuple[bool, Union[dict, str]]:
    try:
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(prompt)
        text = _clean_json_text(getattr(resp, "text", "") or "")
        if not text:
            return False, "Empty model response"

        data = json.loads(text)
        QuizOutput.model_validate(data)
        for q in data.get("quiz", []):
            if isinstance(q.get("difficulty"), str):
                q["difficulty"] = q["difficulty"].lower()
        QuizOutput.model_validate(data)
        return True, data
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

def generate_quiz(url: str, title: str, article_text: str) -> dict[str, Any]:
    article_text = (article_text or "")[:18000]
    prompt = PROMPT_TEMPLATE.format(url=url, title=title, article_text=article_text)

    model_name = _pick_model()
    ok, result = _try_once(model_name, prompt)
    if ok:
        result["url"] = url
        result["title"] = result.get("title") or title
        return result

    nudge_prompt = prompt + "\n\nREMINDER: Return ONLY pure JSON that exactly matches the schema. No markdown."
    ok2, result2 = _try_once(model_name, nudge_prompt)
    if ok2:
        result2["url"] = url
        result2["title"] = result2.get("title") or title
        return result2

    raise RuntimeError(f"Model {model_name} failed. Last error: {result2 if not ok2 else result}")
