# AI Service Backend

Minimal FastAPI backend for the AI Service.

## Local development

Create and activate a virtual environment, then install the project:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Run the development server:

```powershell
fastapi dev app/main.py
```

To enable recipe-improvement turns, set `OPENAI_API_KEY` and
`RECIPE_IMPROVEMENT_OPENAI_MODEL=gpt-5.6-sol` in the backend process environment.
Keep the key in an ignored `backend/.env` file or secret store, never in tracked configuration;
load it into the backend process environment when starting the service.
With either setting missing, the turn endpoint returns `503 generator_unavailable`.
The generator receives the conversation, recipe and available-foodstuff snapshots,
and versioned recipe-specific instructions. It may register validated recipe
proposals through the bounded tool-call flow before returning its reply.

Run the tests:

```powershell
pytest
```
