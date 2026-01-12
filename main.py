import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from requests import HTTPError
from sqlalchemy.exc import IntegrityError

from database import SessionLocal, init_db, Quiz
from scraper import scrape_wikipedia
from llm_quiz_generator import generate_quiz
from cache_manager import check_cache, get_cache_stats

app = FastAPI(title="AI Wiki Quiz Generator API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateBody(BaseModel):
    url: str


@app.on_event("startup")
def on_startup():
    init_db()


@app.get("/")
def root():
    """API root endpoint with basic information."""
    return {
        "name": "AI Wiki Quiz Generator API",
        "version": "1.0.0",
        "endpoints": ["/generate_quiz", "/history", "/quiz/{id}", "/preview", "/cache/stats"]
    }


@app.post("/preview")
def preview_url(body: GenerateBody):
    """
    Preview a Wikipedia URL by fetching just the title.
    Useful for URL validation before generating quiz.
    """
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")
    
    if "wikipedia.org/wiki/" not in url:
        raise HTTPException(status_code=400, detail="URL must be a Wikipedia article")
    
    try:
        title, _, _ = scrape_wikipedia(url)
        return {
            "url": url,
            "title": title,
            "valid": True
        }
    except HTTPError as e:
        code = e.response.status_code if e.response is not None else 500
        if code in (403, 429):
            raise HTTPException(
                status_code=422,
                detail="Wikipedia blocked the request. Please retry in a minute.",
            )
        raise HTTPException(status_code=422, detail="Failed to fetch article")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Error: {str(e)}")


@app.post("/generate_quiz")
def generate_quiz_endpoint(body: GenerateBody):
    """
    Generate a quiz from a Wikipedia URL.
    Checks cache first to avoid duplicate scraping.
    """
    url = body.url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid URL")

    # Check cache first
    db = SessionLocal()
    try:
        cached = check_cache(db, url)
        if cached:
            return cached
    finally:
        db.close()

    # Scrape with UA + mobile fallback; surface clean errors for 403/429
    try:
        title, text, raw_html = scrape_wikipedia(url)
    except HTTPError as e:
        code = e.response.status_code if e.response is not None else 500
        if code in (403, 429):
            raise HTTPException(
                status_code=422,
                detail="Wikipedia blocked the request (403/429). Please retry in a minute or try another page.",
            )
        raise

    if not text or len(text) < 200:
        raise HTTPException(status_code=422, detail="Could not extract sufficient article text")

    try:
        result = generate_quiz(url, title, text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM generation failed: {e}")

    # Store in DB
    db = SessionLocal()
    try:
        record = Quiz(
            url=url,
            title=result.get("title", title),
            scraped_content=text,
            raw_html=raw_html,  # Store raw HTML for reference
            full_quiz_data=json.dumps(result, ensure_ascii=False),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        result_with_id = dict(result)
        result_with_id["id"] = record.id
        result_with_id["cached"] = False
        return result_with_id
    except IntegrityError:
        # URL already exists (race condition), return cached version
        db.rollback()
        cached = check_cache(db, url)
        if cached:
            return cached
        raise HTTPException(status_code=500, detail="Database error")
    finally:
        db.close()


@app.get("/history")
def history():
    """Get list of all generated quizzes."""
    db = SessionLocal()
    try:
        rows = db.query(Quiz).order_by(Quiz.date_generated.desc()).all()
        return [
            {
                "id": r.id,
                "url": r.url,
                "title": r.title,
                "date_generated": r.date_generated.isoformat(),
            }
            for r in rows
        ]
    finally:
        db.close()


@app.get("/quiz/{quiz_id}")
def get_quiz(quiz_id: int):
    """Get full quiz details by ID."""
    db = SessionLocal()
    try:
        r = db.get(Quiz, quiz_id)
        if not r:
            raise HTTPException(status_code=404, detail="Quiz not found")
        data = json.loads(r.full_quiz_data)
        data["id"] = r.id
        data["date_generated"] = r.date_generated.isoformat()
        return data
    finally:
        db.close()


@app.get("/cache/stats")
def cache_stats():
    """Get cache statistics."""
    db = SessionLocal()
    try:
        return get_cache_stats(db)
    finally:
        db.close()

