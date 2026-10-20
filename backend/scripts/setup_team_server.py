"""Create independent team-server credentials without overwriting existing settings."""
from pathlib import Path
import secrets


def main():
    root = Path(__file__).resolve().parents[2]
    target = root / ".env.server"
    try:
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(
                f"POSTGRES_ADMIN_PASSWORD={secrets.token_urlsafe(32)}\n"
                f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n"
                "API_PORT=8000\nITS_API_KEY=\n"
                "CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173\n"
            )
    except FileExistsError:
        print(".env.server already exists; kept unchanged.")
    else:
        print("Created .env.server with separate random passwords. Keep this file private.")


if __name__ == "__main__":
    main()
