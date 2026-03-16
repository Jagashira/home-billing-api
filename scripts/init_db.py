from app.db import init_db
from app.logging import configure_logging


def main() -> None:
    configure_logging()
    init_db()
    print("Database initialized.")


if __name__ == "__main__":
    main()

