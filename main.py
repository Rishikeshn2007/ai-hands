import logging

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI,HTTPException
from tools.news import (
    News,
    NewsConfigurationError,
    NewsInputError,
    NewsServiceError,
)
from tools.weather import Weather

logger = logging.getLogger(__name__)
app=FastAPI()

@app.get('/')
def status():
    return {
        "status":True,
        "message":"Server is running"
    }

@app.get('/news/{news_topic}')
def fetch_news(news_topic : str):
    try:
        return News.get_news(news_topic=news_topic)
    except NewsInputError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NewsConfigurationError as exc:
        logger.error("News embedding service is not configured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NewsServiceError as exc:
        logger.exception("Failed to fetch relevant news for %s", news_topic)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception:
        logger.exception("Unexpected failure fetching news for %s", news_topic)
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )

@app.get('/weather/{city}')
async def fetch_weather(city:str):
    try:
        return await Weather.fetch_weather(city)
    except Exception:
        logger.exception("Failed to fetch weather for %s", city)
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )