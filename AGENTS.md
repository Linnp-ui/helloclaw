# Agent Coding Guidelines

This document provides guidelines for agentic coding agents working in this repository.

## Project Structure

```
├── src/                  # Python backend (FastAPI)
│   ├── api/              # API route handlers
│   ├── agent/            # Agent logic
│   ├── main.py           # Application entry point
│   └── ...
├── frontend/             # Vue.js + TypeScript frontend
│   ├── src/
│   │   ├── api/          # API client functions
│   │   ├── components/   # Vue components
│   │   ├── stores/       # Pinia stores
│   │   ├── utils/        # Utility functions
│   │   └── ...
│   └── package.json
├── test_multimodal_api.py  # Integration tests
└── requirements.txt      # Python dependencies
```

## Build, Lint, and Test Commands

### Backend (Python)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the backend server
PYTHONIOENCODING=utf-8 python -m src.main

# Run a single test file
python test_multimodal_api.py

# Lint with ruff (if configured)
ruff check src/
ruff check src/ --fix  # auto-fix issues
```

### Frontend (Vue.js + TypeScript)

```bash
cd frontend

# Install dependencies
npm install

# Development server
npm run dev

# Build for production
npm run build

# Type check only
npm run type-check

# Preview production build
npm run preview
```

## Code Style Guidelines

### Python (Backend)

**Imports**
- Standard library imports first, then third-party, then local
- Use absolute imports (e.g., `from src.api.chat import ...`)
- Group imports with blank lines between groups

**Formatting**
- Maximum line length: 120 characters (configured in ruff)
- Use Black for code formatting (integrated via ruff)
- Add type hints to function signatures and return types

**Naming Conventions**
- Variables/functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private methods: prefix with `_`

**Type Hints**
```python
from typing import Optional, List

def process_data(items: List[str], verbose: bool = False) -> Optional[str]:
    ...
```

**Error Handling**
- Use try/except for expected errors with specific exception types
- Log errors with appropriate level (`logger.error`, `logger.warning`)
- Return meaningful error messages to API callers

**Docstrings**
- Use Google-style docstrings for public functions
- Include Args, Returns, Raises sections where applicable

```python
def calculate_total(items: List[float]) -> float:
    """Calculate the total sum of items.
    
    Args:
        items: List of numeric values to sum.
        
    Returns:
        The sum of all items.
    """
    return sum(items)
```

### TypeScript (Frontend)

**Imports**
- Use path aliases configured in tsconfig.json when available
- Order: React/Vue imports, then external libs, then internal modules

**Naming**
- Variables/functions: `camelCase`
- Components/Classes: `PascalCase`
- Files: `kebab-case.ts`

**Types**
- Use explicit types for function parameters and return values
- Prefer interfaces for object shapes
- Use `type` for unions and aliases

```typescript
interface ChatMessage {
  id: string;
  content: string;
  role: 'user' | 'assistant';
}

type StreamEvent = 
  | { event: 'chunk'; data: string }
  | { event: 'done' };
```

**Vue Components**
- Use Composition API with `<script setup>`
- Define props with `defineProps<Props>()`
- Use TypeScript in template with v-bind

### General Guidelines

1. **Never commit secrets**: Never add `.env`, credentials, or API keys to version control
2. **Keep functions small**: Single responsibility, max ~50 lines for complex logic
3. **Write meaningful commit messages**: Describe what and why, not just what
4. **Test your changes**: Verify the application runs after modifications
5. **Handle async properly**: Use proper async/await patterns, handle errors in promises

## API Development

When adding new API endpoints:
- Use Pydantic models for request/response validation
- Add proper docstrings describing the endpoint
- Follow RESTful conventions for URL structure
- Return appropriate HTTP status codes

## Common Issues to Avoid

- Don't use `print()` for debugging - use logging
- Don't leave commented-out code in production
- Don't hardcode configuration values - use environment variables
- Don't ignore TypeScript/ruff warnings

## Running Tests

Backend tests can be run directly:
```bash
python test_multimodal_api.py
```

Frontend type checking:
```bash
cd frontend && npm run type-check
```