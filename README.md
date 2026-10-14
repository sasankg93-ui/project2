# Media Processing Service: Week 1

## Run
    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    cp .env.example .env        # fill in bucket, API key
    docker run -d -p 6379:6379 redis:7
    uvicorn app.main:app --reload

AWS credentials come from the standard boto3 chain (env vars, profile, IAM role).
Docs: http://localhost:8000/docs

## Flow
1. `POST /v1/uploads/presign` -> `{source_key, upload_url, headers}`
2. Client `PUT`s the file to `upload_url` with the returned `Content-Type` header.
3. `POST /v1/jobs` with `source_key` + `media_type` -> 202, status `pending`.
4. `GET /v1/jobs/{id}` -> poll status.

All `/v1` routes need an `X-API-Key` header.

## S3 bucket CORS (needed for browser uploads)
    [{"AllowedOrigins":["https://your-app.com"],"AllowedMethods":["PUT"],
      "AllowedHeaders":["Content-Type"],"MaxAgeSeconds":3000}]

## IAM (minimum)
s3:PutObject, s3:GetObject on `arn:aws:s3:::BUCKET/uploads/*`

## Job states
pending -> processing -> completed | failed (failed -> pending for retry).
Workers must use `JobStore.set_status`, which enforces transitions atomically.
