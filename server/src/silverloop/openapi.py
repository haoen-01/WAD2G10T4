import json
from pathlib import Path

from silverloop.main import app


def main() -> None:
    target = Path(__file__).parents[3] / "openapi" / "silverloop.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
