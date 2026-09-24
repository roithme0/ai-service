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

To enable recipe-improvement turns, copy `.env.example` to `.env` and set
`OPENAI_API_KEY`. The backend loads this ignored file automatically and uses
`RECIPE_IMPROVEMENT_OPENAI_MODEL` as the use-case-specific model selection.
Set `KOCHWIKI_BASE_URL` to Kochwiki's API base URL so validated recipe candidates
can be resolved into authoritative presentations before proposal registration.
In deployed environments, supply these values through the process environment or
secret store; never put a real key in tracked configuration. A missing model or
API key makes the turn endpoint return `503 generator_unavailable`. A missing
Kochwiki URL keeps text turns available but makes proposal registration return a
retryable resolver-unavailable result to the model.
The generator receives the conversation, recipe and available-foodstuff snapshots,
and versioned recipe-specific instructions. It may register validated recipe
proposals through the bounded tool-call flow before returning its reply.

Run the tests:

```powershell
pytest
```
