# ai-hands

## News retrieval

`GET /news/{news_topic}` searches DuckDuckGo News, downloads up to five article
pages, extracts their text, and sends the articles to the encoder service for
embedding. Article chunks and their source metadata are stored locally in
`news_vectors.sqlite3`. The topic is embedded with the same service, and the
endpoint returns the five chunks with the highest cosine similarity for the
agent to use as context. This endpoint does not call an LLM.

Configure the encoder API key in the environment before starting the app:

```powershell
$env:ENCODER_API_KEY = "your-encoder-api-key"
uvicorn main:app --reload
```

The encoder URL defaults to `https://encoder-ijir.onrender.com`. Set
`ENCODER_API_URL` to override it. Set `NEWS_VECTOR_DB_PATH` to choose another
location for the local SQLite database. The key is sent only in server-side
requests to the encoder; do not expose it to browser clients.

The response contains `query`, `indexed_articles`, and `results`. Each result
includes the matching article chunk, its source URL and metadata, and its cosine
similarity score. Article pages that cannot be fetched or extracted are skipped.