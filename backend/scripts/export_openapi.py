"""Print the FastAPI OpenAPI document for frontend contract generation."""

import json
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    options = parser.parse_args()
    if options.native:
        from fastapi import FastAPI
        from app.agentic.http import create_session_router

        app = FastAPI()
        app.include_router(create_session_router(lambda: {}))
    else:
        from app.main import app

    print(json.dumps(app.openapi(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
