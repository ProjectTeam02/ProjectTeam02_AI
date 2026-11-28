"""Export the FastAPI <-> Backend tutor contract JSON Schema snapshots.

Usage:
    .venv/bin/python scripts/export_tutor_contract.py          # rewrite snapshots
    .venv/bin/python scripts/export_tutor_contract.py --check  # fail on drift

The snapshots in docs/contracts/ are the reviewable contract artifact shared with
the Backend team. Any schema change must update them in the same PR
(tests/test_tutor_contract.py enforces this).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.schemas.tutor import (  # noqa: E402
    InternalTutorRequest,
    InternalTutorResponse,
)

CONTRACT_DIR = ROOT / "docs" / "contracts"
SNAPSHOTS = {
    "internal_tutor_request.schema.json": (InternalTutorRequest, "validation"),
    "internal_tutor_response.schema.json": (InternalTutorResponse, "serialization"),
}


# Keys that carry contract meaning. Titles/descriptions/defaults vary across
# pydantic 2.x releases (requirements are not pinned), so drift checks ignore them.
CONTRACT_KEYS = {
    "$defs", "$ref", "additionalProperties", "anyOf", "const", "enum", "items",
    "maxItems", "maxLength", "maximum", "minLength", "minimum", "pattern",
    "properties", "required", "type", "format",
}


def normalize(node):
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if key in ("properties", "$defs"):
                out[key] = {name: normalize(child) for name, child in value.items()}
            elif key in CONTRACT_KEYS:
                out[key] = normalize(value)
        if "required" in out:
            out["required"] = sorted(out["required"])
        return out
    if isinstance(node, list):
        return [normalize(item) for item in node]
    return node


def render(model, mode: str) -> str:
    schema = model.model_json_schema(by_alias=True, mode=mode)
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    drift = []
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    for name, (model, mode) in SNAPSHOTS.items():
        path = CONTRACT_DIR / name
        content = render(model, mode)
        if args.check:
            if not path.exists() or normalize(
                json.loads(path.read_text(encoding="utf-8"))
            ) != normalize(json.loads(content)):
                drift.append(name)
        else:
            path.write_text(content, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if drift:
        print("contract snapshot drift: " + ", ".join(drift), file=sys.stderr)
        print("run: .venv/bin/python scripts/export_tutor_contract.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
