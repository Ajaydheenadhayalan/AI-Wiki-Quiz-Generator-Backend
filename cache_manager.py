"""
Cache manager for Wikipedia quiz generation.
Handles checking for existing quizzes and preventing duplicate scraping.
"""
import json
from typing import Optional
from sqlalchemy.orm import Session
from database import Quiz
from datetime import datetime, timedelta


def check_cache(db: Session, url: str) -> Optional[dict]:
    """
    Check if a quiz already exists for the given URL.
    
    Args:
        db: Database session
        url: Wikipedia article URL
        
    Returns:
        Quiz data dict if found, None otherwise
    """
    url = url.strip()
    quiz = db.query(Quiz).filter(Quiz.url == url).first()
    
    if quiz:
        data = json.loads(quiz.full_quiz_data)
        data["id"] = quiz.id
        data["cached"] = True
        data["date_generated"] = quiz.date_generated.isoformat()
        return data
    
    return None


def get_cache_stats(db: Session) -> dict:
    """
    Get cache statistics.
    
    Args:
        db: Database session
        
    Returns:
        Dictionary with cache statistics
    """
    total_quizzes = db.query(Quiz).count()
    recent_quizzes = db.query(Quiz).filter(
        Quiz.date_generated >= datetime.utcnow() - timedelta(days=7)
    ).count()
    
    return {
        "total_cached": total_quizzes,
        "recent_week": recent_quizzes
    }
