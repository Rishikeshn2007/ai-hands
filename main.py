import logging
import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from tools.news import (
    News,
    NewsConfigurationError,
    NewsInputError,
    NewsServiceError,
)
from tools.weather import Weather

logger = logging.getLogger(__name__)
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------------
# API Key Authentication Middleware
# ---------------------------------------------------------------------------
# All routes except GET / require a valid Server-API-Key header.
# Set SERVER_API_KEY in your .env file. Any external server or client that
# knows this key can call the API.
# ---------------------------------------------------------------------------

SERVER_API_KEY = os.getenv("SERVER_API_KEY")

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    # Allow the status endpoint without authentication
    if request.url.path == "/":
        return await call_next(request)

    # Reject requests if SERVER_API_KEY is not configured on the server
    if not SERVER_API_KEY:
        logger.error("SERVER_API_KEY is not set in the environment.")
        return JSONResponse(
            status_code=503,
            content={"detail": "API key authentication is not configured on the server."}
        )

    # Validate the key provided by the caller
    client_key = request.headers.get("Server-API-Key")
    if client_key != SERVER_API_KEY:
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid or missing API key. Provide it via the Server-API-Key header."}
        )

    return await call_next(request)


@app.get('/')
def status():
    return FileResponse("static/index.html")

@app.get('/news/{news_topic}')
def fetch_news(news_topic: str):
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
async def fetch_weather(city: str):
    try:
        return await Weather.fetch_weather(city)
    except Exception:
        logger.exception("Failed to fetch weather for %s", city)
        raise HTTPException(
            status_code=500,
            detail="Internal server error"
        )