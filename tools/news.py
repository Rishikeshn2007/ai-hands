import ipaddress
import json
import logging
import math
import os
import re
import sqlite3
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from ddgs import DDGS

logger = logging.getLogger(__name__)

ENCODER_API_URL = os.getenv(
    "ENCODER_API_URL", "https://encoder-ijir.onrender.com"
).rstrip("/")
VECTOR_DB_PATH = Path(
    os.getenv(
        "NEWS_VECTOR_DB_PATH",
        str(Path(__file__).resolve().parent.parent / "news_vectors.sqlite3"),
    )
)
EMBEDDING_DIMENSION = 384
MAX_ARTICLE_BYTES = 1024 * 1024
MAX_ARTICLES = 5
TOP_K = 5
HTTP_TIMEOUT = 30          # article download timeout (seconds)
EMBEDDING_TIMEOUT = 300    # embedding service timeout — allows for Render cold-starts


class NewsServiceError(Exception):
    """Raised when news retrieval or embedding cannot be completed."""


class NewsConfigurationError(NewsServiceError):
    """Raised when required embedding-service configuration is missing."""


class NewsInputError(NewsServiceError):
    """Raised when the requested news query is invalid."""


class ArticleTextParser(HTMLParser):
    _ignored_tags = {
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "footer",
        "header",
        "aside",
        "form",
        "iframe",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._article_depth = 0
        self._main_depth = 0
        self._paragraph_depth = 0
        self._article_text: list[str] = []
        self._main_text: list[str] = []
        self._paragraph_text: list[str] = []

    def handle_starttag(
        self, tag: str, _attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in self._ignored_tags:
            self._ignored_depth += 1
        if self._ignored_depth:
            return
        if tag == "img":
            alt_text = dict(_attrs).get("alt", "")
            if alt_text:
                if self._article_depth:
                    self._article_text.append(alt_text)
                if self._main_depth:
                    self._main_text.append(alt_text)
                if self._paragraph_depth:
                    self._paragraph_text.append(alt_text)
        if tag == "article":
            self._article_depth += 1
        if tag == "main":
            self._main_depth += 1
        if tag == "p":
            self._paragraph_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._ignored_tags and self._ignored_depth:
            self._ignored_depth -= 1
        if self._ignored_depth:
            return
        if tag == "article" and self._article_depth:
            self._article_depth -= 1
        if tag == "main" and self._main_depth:
            self._main_depth -= 1
        if tag == "p" and self._paragraph_depth:
            self._paragraph_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._article_depth:
            self._article_text.append(text)
        if self._main_depth:
            self._main_text.append(text)
        if self._paragraph_depth:
            self._paragraph_text.append(text)

    def get_text(self) -> str:
        candidates = (
            self._article_text,
            self._main_text,
            self._paragraph_text,
        )
        for candidate in candidates:
            text = re.sub(r"\s+", " ", " ".join(candidate)).strip()
            if len(text) >= 200:
                return text
        return ""


def _validate_public_http_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NewsServiceError("News search returned an invalid article URL.")
    if parsed.username or parsed.password:
        raise NewsServiceError("News search returned an invalid article URL.")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        raise NewsServiceError("News search returned an invalid article URL.")


def _initialize_database() -> None:
    VECTOR_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(VECTOR_DB_PATH)
    try:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS news_chunks (
                    url TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    publisher TEXT,
                    published_at TEXT,
                    text TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    PRIMARY KEY (url, chunk_index)
                )
                """
            )
    finally:
        connection.close()


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    dot_product = math.fsum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(math.fsum(value * value for value in left))
    right_norm = math.sqrt(math.fsum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot_product / (left_norm * right_norm)


class News:
    @staticmethod
    def _get_api_key() -> str:
        api_key = os.getenv("ENCODER_API_KEY")
        if not api_key:
            raise NewsConfigurationError(
                "ENCODER_API_KEY is required to call the embedding service."
            )
        return api_key

    @staticmethod
    def _download_article(client: httpx.Client, url: str) -> str:
        _validate_public_http_url(url)
        try:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type.lower():
                    return ""
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_ARTICLE_BYTES:
                    logger.info("Skipping oversized article %s", url)
                    return ""
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_ARTICLE_BYTES:
                        logger.info("Skipping oversized article %s", url)
                        return ""
            parser = ArticleTextParser()
            parser.feed(bytes(body).decode(response.encoding or "utf-8", errors="replace"))
            text = parser.get_text()
            encoded_text = text.encode("utf-8")[:MAX_ARTICLE_BYTES]
            return encoded_text.decode("utf-8", errors="ignore")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code < 500:
                # 4xx errors (403 Forbidden, 404 Not Found, etc.) are expected
                # for paywalled or restricted articles — skip silently.
                logger.debug("Skipping article %s: HTTP %s", url, exc.response.status_code)
            else:
                logger.warning("Unable to fetch article %s: %s", url, exc)
            return ""
        except (httpx.HTTPError, UnicodeError, ValueError) as exc:
            logger.warning("Unable to fetch article %s: %s", url, exc)
            return ""

    @staticmethod
    def _embed_documents(
        client: httpx.Client,
        articles: list[dict[str, str]],
        api_key: str,
    ) -> list[dict[str, object]]:
        files = [
            (
                "files",
                (
                    f"article-{index}.txt",
                    article["text"].encode("utf-8"),
                    "text/plain",
                ),
            )
            for index, article in enumerate(articles)
        ]
        response = client.post(
            f"{ENCODER_API_URL}/api/embed-documents",
            headers={"X-API-Key": api_key},
            files=files,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise NewsServiceError(
                payload.get("error", "The embedding service rejected the articles.")
            )
        if payload.get("embedding_dimension") != EMBEDDING_DIMENSION:
            raise NewsServiceError("The embedding service returned an unexpected dimension.")

        documents = payload.get("documents")
        if not isinstance(documents, list) or len(documents) != len(articles):
            raise NewsServiceError("The embedding service returned invalid document data.")

        chunks: list[dict[str, object]] = []
        for article, document in zip(articles, documents):
            returned_chunks = document.get("chunks", [])
            if not isinstance(returned_chunks, list):
                raise NewsServiceError("The embedding service returned invalid chunks.")
            for chunk in returned_chunks:
                embedding = chunk.get("embedding")
                chunk_index = chunk.get("chunk_index")
                if (
                    not isinstance(embedding, list)
                    or len(embedding) != EMBEDDING_DIMENSION
                    or not isinstance(chunk_index, int)
                    or not isinstance(chunk.get("text"), str)
                ):
                    raise NewsServiceError(
                        "The embedding service returned invalid chunk data."
                    )
                try:
                    vector = [float(value) for value in embedding]
                except (TypeError, ValueError) as exc:
                    raise NewsServiceError(
                        "The embedding service returned an invalid vector."
                    ) from exc
                if not all(math.isfinite(value) for value in vector):
                    raise NewsServiceError(
                        "The embedding service returned an invalid vector."
                    )
                chunks.append(
                    {
                        "url": article["url"],
                        "title": article["title"],
                        "publisher": article.get("publisher"),
                        "published_at": article.get("published_at"),
                        "chunk_index": chunk_index,
                        "text": chunk["text"],
                        "embedding": vector,
                    }
                )
        return chunks

    @staticmethod
    def _store_chunks(chunks: list[dict[str, object]]) -> None:
        _initialize_database()
        connection = sqlite3.connect(VECTOR_DB_PATH)
        try:
            with connection:
                for url in {chunk["url"] for chunk in chunks}:
                    connection.execute(
                        "DELETE FROM news_chunks WHERE url = ?",
                        (url,),
                    )
                connection.executemany(
                    """
                    INSERT INTO news_chunks (
                        url, chunk_index, title, publisher, published_at, text, embedding
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url, chunk_index) DO UPDATE SET
                        title = excluded.title,
                        publisher = excluded.publisher,
                        published_at = excluded.published_at,
                        text = excluded.text,
                        embedding = excluded.embedding
                    """,
                    [
                        (
                            chunk["url"],
                            chunk["chunk_index"],
                            chunk["title"],
                            chunk["publisher"],
                            chunk["published_at"],
                            chunk["text"],
                            json.dumps(chunk["embedding"]),
                        )
                        for chunk in chunks
                    ],
                )
        finally:
            connection.close()

    @staticmethod
    def _embed_query(client: httpx.Client, query: str, api_key: str) -> list[float]:
        response = client.post(
            f"{ENCODER_API_URL}/api/embed-query",
            headers={"X-API-Key": api_key},
            json={"query": query},
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise NewsServiceError(
                payload.get("error", "The embedding service rejected the query.")
            )
        embedding = payload.get("embedding")
        if (
            not isinstance(embedding, list)
            or len(embedding) != EMBEDDING_DIMENSION
        ):
            raise NewsServiceError("The embedding service returned an invalid query vector.")
        try:
            vector = [float(value) for value in embedding]
        except (TypeError, ValueError) as exc:
            raise NewsServiceError(
                "The embedding service returned an invalid query vector."
            ) from exc
        if not all(math.isfinite(value) for value in vector):
            raise NewsServiceError("The embedding service returned an invalid query vector.")
        return vector

    @staticmethod
    def _search_vectors(query_vector: list[float], limit: int) -> list[dict[str, object]]:
        _initialize_database()
        connection = sqlite3.connect(VECTOR_DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            rows = connection.execute(
                """
                SELECT url, title, publisher, published_at, chunk_index, text, embedding
                FROM news_chunks
                """
            ).fetchall()
        finally:
            connection.close()

        results = []
        for row in rows:
            embedding = json.loads(row["embedding"])
            results.append(
                {
                    "url": row["url"],
                    "title": row["title"],
                    "publisher": row["publisher"],
                    "published_at": row["published_at"],
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "similarity": _cosine_similarity(query_vector, embedding),
                }
            )
        results.sort(key=lambda result: result["similarity"], reverse=True)
        return results[:limit]

    @staticmethod
    def get_news(news_topic: str, limit: int = TOP_K) -> dict[str, object]:
        topic = news_topic.strip()
        if not topic:
            raise NewsInputError("news_topic must not be empty.")
        if len(topic) > 2000:
            raise NewsInputError("news_topic must not exceed 2,000 characters.")
        if not 1 <= limit <= 20:
            raise NewsInputError("limit must be between 1 and 20.")
        api_key = News._get_api_key()

        try:
            search_results = DDGS().news(
                topic,
                region="in-en",
                max_results=MAX_ARTICLES,
            )
        except Exception as exc:
            logger.exception("News search failed for %s", topic)
            raise NewsServiceError("News search is temporarily unavailable.") from exc

        articles: list[dict[str, str]] = []
        seen_urls: set[str] = set()

        # --- Step 1: download articles (short timeout) ---
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True) as download_client:
                for result in search_results:
                    url = result.get("url")
                    if not isinstance(url, str) or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    try:
                        text = News._download_article(download_client, url)
                    except NewsServiceError as exc:
                        logger.warning("Skipping article %s: %s", url, exc)
                        continue
                    if not text:
                        continue
                    articles.append(
                        {
                            "url": url,
                            "title": str(result.get("title") or ""),
                            "publisher": str(result.get("source") or ""),
                            "published_at": str(result.get("date") or ""),
                            "text": text,
                        }
                    )
                    if len(articles) == MAX_ARTICLES:
                        break
        except httpx.HTTPError as exc:
            logger.exception("Article download HTTP request failed")
            raise NewsServiceError(
                "Failed to download news articles."
            ) from exc

        # --- Step 2: embed & index new articles + embed query (long timeout) ---
        # Document embedding is best-effort: if the encoder is cold-starting or
        # slow, we skip indexing new articles and fall back to the cached DB.
        try:
            with httpx.Client(timeout=EMBEDDING_TIMEOUT, follow_redirects=True) as embed_client:
                if articles:
                    try:
                        chunks = News._embed_documents(embed_client, articles, api_key)
                        if chunks:
                            News._store_chunks(chunks)
                    except (httpx.HTTPError, NewsServiceError) as exc:
                        logger.warning(
                            "Skipping document embedding (will use cached results): %s", exc
                        )
                        articles = []  # don't claim we indexed articles we couldn't embed

                query_vector = News._embed_query(embed_client, topic, api_key)
        except httpx.HTTPError as exc:
            logger.exception("Embedding service HTTP request failed")
            raise NewsServiceError(
                "The embedding service is temporarily unavailable."
            ) from exc

        matches = News._search_vectors(query_vector, limit)
        return {
            "query": topic,
            "indexed_articles": len(articles),
            "results": matches,
        }
