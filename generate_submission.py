"""
Generate canonical submission.jsonl for all 30 test pairs in test_pairs.json.
Conforms to challenge-brief.md §7.2.
"""

import json
from pathlib import Path
from composer import compose

ROOT_DIR = Path(__file__).parent
EXPANDED_DIR = ROOT_DIR / "expanded"


def main():
    test_pairs_path = EXPANDED_DIR / "test_pairs.json"
    with open(test_pairs_path, "r", encoding="utf-8") as f:
        pairs_data = json.load(f)["pairs"]

    # Load categories
    categories = {}
    for f in (EXPANDED_DIR / "categories").glob("*.json"):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
            categories[d.get("slug", f.stem)] = d

    # Load merchants
    merchants = {}
    for f in (EXPANDED_DIR / "merchants").glob("*.json"):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
            merchants[d.get("merchant_id", f.stem)] = d

    # Load customers
    customers = {}
    for f in (EXPANDED_DIR / "customers").glob("*.json"):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
            customers[d.get("customer_id", f.stem)] = d

    # Load triggers
    triggers = {}
    for f in (EXPANDED_DIR / "triggers").glob("*.json"):
        with open(f, "r", encoding="utf-8") as fp:
            d = json.load(fp)
            triggers[d.get("id", f.stem)] = d

    submission_lines = []

    for pair in pairs_data:
        test_id = pair["test_id"]
        tid = pair["trigger_id"]
        mid = pair["merchant_id"]
        cid = pair.get("customer_id")

        trg = triggers.get(tid)
        if not trg:
            # Fallback search
            trg = next((t for t in triggers.values() if t.get("id") == tid), {})

        merch = merchants.get(mid)
        if not merch:
            merch = next((m for m in merchants.values() if m.get("merchant_id") == mid), {})

        cat_slug = merch.get("category_slug") or trg.get("payload", {}).get("category", "dentists")
        cat = categories.get(cat_slug, {})

        cust = customers.get(cid) if cid else None

        res = compose(cat, merch, trg, cust)

        line = {
            "test_id": test_id,
            "body": res["body"],
            "cta": res["cta"],
            "send_as": res["send_as"],
            "suppression_key": res["suppression_key"],
            "rationale": res["rationale"]
        }
        submission_lines.append(line)

    out_path = ROOT_DIR / "submission.jsonl"
    with open(out_path, "w", encoding="utf-8") as out_f:
        for item in submission_lines:
            out_f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Generated {len(submission_lines)} test submissions in {out_path}")


if __name__ == "__main__":
    main()
