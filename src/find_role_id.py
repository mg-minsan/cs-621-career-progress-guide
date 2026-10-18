"""Look up framework role ids by name, for filling in evals/e1_personas.json.

    py src/find_role_id.py "Data Analyst"

This only matches NAMES. It deliberately does not suggest next roles: E1
labels must come from the sector guides / your own judgement, not from the
agent's method (no contamination)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lookups import find_roles  # noqa: E402

for r in find_roles(" ".join(sys.argv[1:]) or "Data Analyst", limit=10):
    print(f"  [{r['role_id']:>4}] {r['sector']} / {r['track']} / {r['role']}   (name match {r['score']})")
