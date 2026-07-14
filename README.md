# AgentMesh

> **The LLM decides what to do. AgentMesh decides how to do it.**

A distributed AI workflow execution engine that converts natural language requests into executable workflow graphs and reliably executes them across asynchronous workers using a pluggable tool runtime.

## Architecture

```
User Request → Planner (LLM) → Compiler (DAG) → Scheduler → Redis Queue → Workers → Tools → Results
```

## Quick Start

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (for local development)

### Run with Docker
```bash
docker compose up --build
```

API available at: http://localhost:8000
Docs available at: http://localhost:8000/docs

### Local Development
```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -e ".[dev]"

# Copy environment file
cp .env.example .env

# Start PostgreSQL and Redis (via Docker)
docker compose up postgres redis -d

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn agentmesh.main:app --reload

# Run tests
pytest -v
```

## API Usage

### Create a Workflow
```bash
curl -X POST http://localhost:8000/api/v1/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "tasks": [
      {"id": "fetch", "tool": "http", "params": {"url": "https://api.example.com"}, "depends_on": []},
      {"id": "process", "tool": "llm", "params": {"prompt": "summarize"}, "depends_on": ["fetch"]},
      {"id": "save", "tool": "filesystem", "params": {"path": "report.md"}, "depends_on": ["process"]}
    ]
  }'
```

### Check Health
```bash
curl http://localhost:8000/health
```

### Authentication (optional)
Every request is unauthenticated by default. Set `API_KEY` in `.env` to
require a matching `X-API-Key` header on every request except `/health`,
`/docs`, `/redoc`, and the WebSocket stream.

## Demo

See [docs/demo.md](docs/demo.md) for a full end-to-end run — fetch the
Hacker News front page, summarize it with Gemini, and save the digest to
disk — using the workflow spec in [examples/hn_digest_workflow.json](examples/hn_digest_workflow.json).

## Project Structure
```
agentmesh/
├── api/            # FastAPI routes and WebSocket handlers
├── middleware/     # Correlation-ID and API-key ASGI middleware
├── observability/  # Structured logging setup
├── models/         # SQLAlchemy ORM models
├── schemas/        # Pydantic request/response schemas
├── persistence/    # Database engine, sessions, repository
├── scheduler/      # In-process executor, distributed coordinator, startup recovery
├── worker/         # Standalone Redis Streams worker process
├── tools/          # Pluggable tool runtime (http, llm, filesystem, shell, echo)
├── config.py       # Pydantic Settings configuration
└── main.py         # FastAPI application entrypoint

alembic/            # Database migration scripts
examples/           # Example workflow specs (see docs/demo.md)
frontend/           # React + TypeScript dashboard
tests/              # Pytest test suite
docs/               # Architecture, API reference, implementation plan, demo
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + asyncio |
| Database | PostgreSQL 16 + SQLAlchemy 2.0 |
| Queue | Redis 7 Streams |
| AI | Google Gemini API |
| Frontend | React + TypeScript + React Flow |
| Infra | Docker Compose |

## Documentation

- [Architecture](docs/architecture.md)
- [Implementation Plan](docs/implementation-plan.md)
- [Tech Stack](docs/tech-stack.md)
- [Database Schema](docs/database-schema.md)
- [API Reference](docs/api-reference.md)
- [Roadmap](docs/roadmap.md)
- [Demo Walkthrough](docs/demo.md)
- [Contributing](docs/contributing.md)

## License

MIT
