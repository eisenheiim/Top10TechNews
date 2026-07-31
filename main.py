import json

from pipeline import run


def main() -> None:
    payload = run(save=True)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    with open("ui_payload.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("\nWrote ui_payload.json and history/")


if __name__ == "__main__":
    main()
