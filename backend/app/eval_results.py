"""The eval results written by evals/run_evals.py, as served by GET /evals/latest.

Read as plain JSON: the app does not depend on the eval harness.
"""

import json
from pathlib import Path
from typing import Any

from app.config import BACKEND_DIR

# The scored results. The raw run outputs are in its raw/ subfolder.
EVAL_RESULTS_DIR = BACKEND_DIR / "evals" / "results"


def latest_eval_results(directory: Path = EVAL_RESULTS_DIR) -> list[dict[str, Any]]:
    """The newest result of each model, newest first. Empty if there are none.

    File names start with a UTC timestamp, so sorting by name sorts by time.
    """
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.json"), reverse=True):
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
            model = result["meta"]["model"]
        except (OSError, ValueError, KeyError, TypeError):
            continue  # not an eval result
        latest.setdefault(model, result)
    return list(latest.values())
