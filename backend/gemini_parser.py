from google import genai
import os
import json
import re
import hashlib
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

# ─── IN-MEMORY CACHE ─────────────────────────────────────────────────────────
# Survives for the lifetime of the Flask process
_cache = {}

def _cache_key(*args) -> str:
    raw = "|".join(str(a) for a in args)
    return hashlib.md5(raw.encode()).hexdigest()

def _from_cache(key):
    return _cache.get(key)

def _to_cache(key, value):
    _cache[key] = value


# ─── PROMPTS ─────────────────────────────────────────────────────────────────

PARSE_PROMPT = """
You are a humanitarian data analyst. Extract structured information from the following NGO field report.

Return ONLY a valid JSON object with these exact fields:
{{
  "category": "one of: medical, food, education, logistics, shelter, mental_health, other",
  "urgency": "one of: critical, high, medium, low",
  "people_affected": <integer>,
  "location": "<city or area name>",
  "summary": "<one sentence summary>"
}}

Do NOT include any text outside the JSON object.

Field report:
{text}
"""

# KEY CHANGE: One prompt for ALL volunteers at once
BATCH_MATCH_PROMPT = """
You are evaluating volunteer-to-need compatibility for humanitarian work.

Need description: {need_description}
Need category: {need_category}

Score each volunteer's skills for relevance to this need (0-10).

Volunteers:
{volunteers_list}

Return ONLY a JSON array, one entry per volunteer, in the same order:
[
  {{"id": "<volunteer_id>", "relevance_score": <0-10>, "reason": "<short phrase>"}},
  ...
]

Do NOT include any text outside the JSON array.
"""

SITUATION_SUMMARY_PROMPT = """
You are a humanitarian coordinator assistant.

Needs data:
{needs_json}

Write a 2-3 sentence summary covering total people affected, critical gaps, and one immediate action.
Return plain text only.
"""


# ─── HELPERS ─────────────────────────────────────────────────────────────────

def extract_json(text: str):
    text = re.sub(r"```json|```", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    # Also handle arrays
    arr_start = text.find("[")
    if arr_start != -1 and (start == -1 or arr_start < start):
        start = arr_start
        end = text.rfind("]")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON found in: {text}")
    json_str = text[start:end+1]
    json_str = re.sub(r",\s*}", "}", json_str)
    json_str = re.sub(r",\s*]", "]", json_str)
    return json.loads(json_str)


def get_text_from_response(response):
    try:
        if hasattr(response, "text") and response.text:
            return response.text.strip()
    except:
        pass
    try:
        return response.candidates[0].content.parts[0].text.strip()
    except:
        pass
    return ""


def call_gemini(prompt: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.0-flash-lite",
        contents=prompt
    )
    return get_text_from_response(response)


def is_quota_error(err: str) -> bool:
    return "429" in err or "RESOURCE_EXHAUSTED" in err or "quota" in err.lower()


# ─── FALLBACKS ───────────────────────────────────────────────────────────────

def parse_need_fallback(text: str) -> dict:
    t = text.lower()
    if any(w in t for w in ["flood", "disaster", "critical", "emergency", "no food for", "no water for", "stranded"]):
        urgency = "critical"
    elif any(w in t for w in ["urgent", "immediate", "sick", "shortage", "injured"]):
        urgency = "high"
    elif any(w in t for w in ["need", "require", "support", "help"]):
        urgency = "medium"
    else:
        urgency = "low"

    if any(w in t for w in ["medical", "doctor", "nurse", "health", "hospital", "paramedic"]):
        category = "medical"
    elif any(w in t for w in ["food", "water", "meal", "hungry", "nutrition", "ration"]):
        category = "food"
    elif any(w in t for w in ["shelter", "house", "camp", "roof", "displaced"]):
        category = "shelter"
    elif any(w in t for w in ["transport", "logistics", "supply", "distribution"]):
        category = "logistics"
    elif any(w in t for w in ["counsel", "mental", "trauma", "psycho"]):
        category = "mental_health"
    elif any(w in t for w in ["teach", "school", "education", "student"]):
        category = "education"
    else:
        category = "other"

    numbers = re.findall(r'\b(\d+)\b', text)
    people = int(numbers[0]) if numbers else 50
    summary = (text[:120] + "...") if len(text) > 120 else text
    return {
        "category": category,
        "urgency": urgency,
        "people_affected": people,
        "location": "Unknown",
        "summary": summary
    }


def keyword_relevance(need_description: str, need_category: str, volunteer_skills: str) -> dict:
    need_words = set(need_category.lower().split() + need_description.lower().split())
    vol_words = set(volunteer_skills.lower().replace(",", " ").split())
    overlap = len(need_words & vol_words)
    score = min(10, overlap * 2 + 3)
    return {"relevance_score": score, "reason": "keyword match (fallback)"}


# ─── MAIN FUNCTIONS ──────────────────────────────────────────────────────────

def parse_need(text: str) -> dict:
    # Check cache first — same text never calls Gemini twice
    key = _cache_key("parse", text)
    cached = _from_cache(key)
    if cached:
        print("✅ Cache hit — parse_need")
        return {"success": True, "data": cached, "source": "cache"}

    try:
        prompt = PARSE_PROMPT.format(text=text)
        raw = call_gemini(prompt)
        print(f"\n==== GEMINI PARSE ====\n{raw}\n======================\n")
        parsed = extract_json(raw)
        for field in ["category", "urgency", "people_affected", "location", "summary"]:
            if field not in parsed:
                raise ValueError(f"Missing field: {field}")
        _to_cache(key, parsed)
        return {"success": True, "data": parsed, "source": "gemini"}

    except Exception as e:
        err = str(e)
        if is_quota_error(err):
            print("⚠️  Quota exceeded — using rule-based fallback")
            return {"success": True, "data": parse_need_fallback(text), "source": "fallback"}
        print(f"❌ Error: {err}")
        return {"success": False, "error": err}


def get_batch_skill_relevance(need: dict, volunteers: list) -> list:
    """
    ONE Gemini call for all volunteers instead of one per volunteer.
    Reduces calls from 8 → 1 per need.
    """
    need_desc = need.get("description", "")
    need_cat = need.get("category", "")

    # Cache key based on need + all volunteer ids
    vol_ids = [str(v.get("id", "")) for v in volunteers]
    key = _cache_key("batch_match", need_desc, need_cat, *vol_ids)
    cached = _from_cache(key)
    if cached:
        print("✅ Cache hit — batch skill match")
        return cached

    # Build volunteers list for prompt
    vol_lines = "\n".join([
        f"- id: {v.get('id')} | skills: {v.get('skills', '')}"
        for v in volunteers
    ])

    try:
        prompt = BATCH_MATCH_PROMPT.format(
            need_description=need_desc,
            need_category=need_cat,
            volunteers_list=vol_lines
        )
        raw = call_gemini(prompt)
        print(f"\n==== GEMINI BATCH MATCH ====\n{raw}\n============================\n")
        results = extract_json(raw)

        if not isinstance(results, list):
            raise ValueError("Expected a JSON array")

        _to_cache(key, results)
        return results

    except Exception as e:
        err = str(e)
        if is_quota_error(err):
            print("⚠️  Quota exceeded — using keyword fallback for batch match")
        # Fallback: keyword match for each volunteer
        return [
            {
                "id": v.get("id"),
                **keyword_relevance(need_desc, need_cat, v.get("skills", ""))
            }
            for v in volunteers
        ]


def get_skill_relevance(need_description: str, need_category: str, volunteer_skills: str) -> dict:
    """Single volunteer match — kept for backward compatibility."""
    key = _cache_key("skill", need_description, need_category, volunteer_skills)
    cached = _from_cache(key)
    if cached:
        print("✅ Cache hit — skill relevance")
        return cached

    try:
        prompt = f"""
You are evaluating volunteer-to-need compatibility.

Need: {need_description}
Need Category: {need_category}
Volunteer skills: {volunteer_skills}

Return ONLY JSON:
{{"relevance_score": <0-10>, "reason": "<short phrase>"}}
"""
        raw = call_gemini(prompt)
        result = extract_json(raw)
        _to_cache(key, result)
        return result

    except Exception as e:
        err = str(e)
        if is_quota_error(err):
            print("⚠️  Quota exceeded — keyword fallback")
        return keyword_relevance(need_description, need_category, volunteer_skills)


def generate_situation_summary(needs: list) -> str:
    """Cached — only regenerates if needs data changes."""
    key = _cache_key("summary", json.dumps(needs, sort_keys=True))
    cached = _from_cache(key)
    if cached:
        print("✅ Cache hit — situation summary")
        return cached

    try:
        prompt = SITUATION_SUMMARY_PROMPT.format(
            needs_json=json.dumps(needs, indent=2)
        )
        result = call_gemini(prompt)
        _to_cache(key, result)
        return result

    except Exception as e:
        err = str(e)
        if is_quota_error(err):
            print("⚠️  Quota exceeded — static summary")
        total = sum(int(n.get("people_affected", 0)) for n in needs)
        critical = len([n for n in needs if n.get("urgency") == "critical"])
        return (
            f"{len(needs)} active needs affecting approximately {total} people. "
            f"{critical} critical situation(s) require immediate attention. "
            f"Recommend deploying available volunteers to highest priority locations first."
        )