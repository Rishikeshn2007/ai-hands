import logging

from fastapi import FastAPI,HTTPException
from tools.news import News
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
        data=News.get_news(news_topic=news_topic)
        return data
    except Exception:
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