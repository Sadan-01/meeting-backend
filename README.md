# MeetMind AI Backend

MeetMind AI is an AI SaaS backend foundation built with FastAPI, SQLAlchemy, SQLite, and Pydantic v2. This module establishes the production-ready project structure, configuration system, database wiring, logging, and base API endpoints needed for future application modules.

Authentication and AI features are intentionally not included in Module 1.

## Folder Structure

```text
backend/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   └── root.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── logging.py
│   ├── database/
│   │   ├── __init__.py
│   │   └── database.py
│   ├── logs/
│   │   └── .gitkeep
│   ├── models/
│   │   └── __init__.py
│   ├── schemas/
│   │   └── __init__.py
│   ├── services/
│   │   └── __init__.py
│   ├── uploads/
│   │   └── .gitkeep
│   └── utils/
│       └── __init__.py
├── .env.example
├── .gitignore
├── main.py
├── README.md
└── requirements.txt
```

## Installation

Clone the project and move into the backend directory:

```bash
cd backend
```

Install the project dependencies:

```bash
pip install -r requirements.txt
```

## Virtual Environment

Create and activate a virtual environment before installing dependencies.

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
```

## Environment Configuration

Create a local `.env` file from the example file:

```bash
cp .env.example .env
```

Update the values in `.env` for the target environment. The default SQLite database URL uses `meeting.db`:

```env
DATABASE_URL="sqlite:///./meeting.db"
```

## Running FastAPI

Start the development server with Uvicorn:

```bash
uvicorn main:app --reload
```

The backend will be available at:

```text
http://127.0.0.1:8000
```

## Swagger URL

Interactive API documentation is available at:

```text
http://127.0.0.1:8000/docs
```

## Available Endpoints

```text
GET /
GET /health
```

