# eMAS API

Go backend for eMAS (Manufacturing / Production Management System).

## Tech Stack

- **Language:** Go (Golang)
- **Web Framework:** Gin
- **ORM:** GORM
- **Database:** MySQL
- **Logging:** Zap

## Project Structure

```
emas/
├── cmd/emas/main.go      # Entry point
├── config/               # App config, env vars
├── internal/             # Domain, repository, service, handler
├── pkg/                  # Logger, utils
├── migrations/           # DB migrations
├── scripts/              # Seeders, cron tasks
└── api/swagger/          # OpenAPI docs
```

## Setup

1. Copy `.env.example` to `.env` and configure
2. Create MySQL database `emas`
3. Run:
   ```bash
   go mod tidy
   go run ./cmd/emas
   ```

## Endpoints

- `GET /health` - Health check
