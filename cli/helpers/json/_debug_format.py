"""Reformat lines containing JSON for readability."""

from __future__ import annotations

import json

from cli.helpers.json._serialization import compact


def reformat_json_lines(text: str) -> str:
    """Reformat JSON blobs in prose text for readability.

    Splits on newlines, tries ``json.loads`` on each line, and replaces
    parseable ones with compact output.  This handles minified JSON lines
    (including those inside markdown code fences) while leaving non-JSON
    lines untouched.
    """
    lines = text.split("\n")
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            result.append(line)
            continue
        try:
            obj = json.loads(stripped)
            result.append(compact(obj))
        except (json.JSONDecodeError, ValueError):
            result.append(line)
    return "\n".join(result)
