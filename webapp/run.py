"""Entry point for running the webapp via `uv run scouting-webapp`."""

import uvicorn


def main():
    uvicorn.run("webapp.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
