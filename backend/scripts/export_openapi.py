"""Print the FastAPI OpenAPI document for frontend contract generation."""

import json
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true")
    parser.add_argument("--transcription", action="store_true")
    options = parser.parse_args()
    if options.native and options.transcription:
        parser.error("Choose one router export")
    if options.native or options.transcription:
        from fastapi import FastAPI

        app = FastAPI()
        if options.native:
            from app.capabilities.conversations.http import create_session_router

            app.include_router(create_session_router(lambda: {}))
        else:
            from app.capabilities.transcriptions.http import router

            app.include_router(router)
    else:
        from app.main import app

    print(json.dumps(app.openapi(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
