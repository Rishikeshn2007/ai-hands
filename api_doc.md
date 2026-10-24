# Embedding Backend

A stateless FastAPI backend that accepts UTF-8 `.txt` files, splits them into overlapping word chunks, and creates 384-dimensional embeddings with `sentence-transformers/all-MiniLM-L6-v2`. It has no database, vector search, similarity logic, LLM, or persistent file/vector storage.

## Local setup

Create and activate a virtual environment in this project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install dependencies and run the API:

```powershell
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The first embedding request downloads and loads the model; subsequent requests reuse it while the process remains warm. Open `test_client.html` directly in a browser. Its `BACKEND_URL` defaults to `http://localhost:8000`; it displays uploaded filenames, chunk totals, vector dimension, a preview, and complete response JSON.

## API

`GET /api/health` returns:

```json
{"success":true,"service":"embedding-backend"}
```

`POST /api/embed-documents` accepts `multipart/form-data`, with one or more fields named `files`. There can be at most 10 `.txt` files, each at most 1 MiB. Files must be non-empty and valid UTF-8. Whitespace is normalized before splitting into 500-word chunks with 50-word overlap.

```json
{"success":true,"embedding_model":"sentence-transformers/all-MiniLM-L6-v2","embedding_dimension":384,"documents":[{"document_id":"uuid","filename":"notes.txt","character_count":42,"chunk_count":1,"chunks":[{"chunk_id":"uuid","chunk_index":0,"text":"...","embedding":[0.1]}]}]}
```

Every real `embedding` array contains exactly 384 numbers. Document IDs and chunk IDs are generated for each response.

```powershell
curl.exe -X POST http://localhost:8000/api/embed-documents -H "X-API-Key: YOUR_API_KEY" -F "files=@example.txt;type=text/plain"
curl.exe -X POST http://localhost:8000/api/embed-query -H "X-API-Key: YOUR_API_KEY" -H "Content-Type: application/json" -d '{\"query\":\"What is database normalization?\"}'
```

`POST /api/embed-query` accepts `{"query":"What is database normalization?"}`. `query` must be a non-empty string after trimming and no more than 2,000 characters. It returns `success`, `embedding_model`, `embedding_dimension`, the trimmed `query`, and a 384-number `embedding` array. Validation and operational errors consistently use `{"success": false, "error": "..."}` and an appropriate HTTP status.

## CORS and Vercel

Set `API_KEY` to a long, random secret. Both embedding endpoints require it in the `X-API-Key` request header; missing or incorrect keys receive HTTP 401. If the server has no `API_KEY` configured, embedding requests receive HTTP 503 rather than being allowed through. `GET /api/health` remains public.

For local PowerShell development, set the key in the shell before starting Uvicorn, for example `$env:API_KEY = "your-local-secret"`. Also set `FRONTEND_ORIGIN` to your frontend origin if needed; multiple comma-separated origins are supported, and common localhost ports are allowed automatically. `.env.example` documents the variables but is not loaded automatically.

`api/index.py` is the ASGI entry point and Vercel routes API requests to it. Deploy the repository from the Vercel dashboard or CLI; Vercel installs `requirements.txt`. Configure `API_KEY` and, if needed, `FRONTEND_ORIGIN` as Vercel project environment variables, then redeploy. Do not commit a real secret or put the key in browser-side JavaScript: anyone who can inspect a browser request can copy that key. Send it only from trusted server-side callers.

Sentence Transformers and PyTorch are large serverless dependencies. On Vercel, expect cold starts while the model initializes (or downloads if not cached), significant memory use, and execution-time limits. Confirm that your Vercel plan’s Python memory, function size, and timeout allowances fit this model. This design caches the model only in a warm function process; it intentionally stores neither uploads, chunks, nor vectors after the response is sent.
