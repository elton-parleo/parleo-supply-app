"""
scripts/migrate_deal_details.py

One-time data migration: rename stale deal_details keys to the unified schema.

Field renames applied:
  "percent"               → "discount_percent"
  "minimum_order_value"   → "spend_min"
  "points_multiplier"     → "earn_multiplier"
  "applicable_categories" → "scope_categories"

Usage:
  python scripts/migrate_deal_details.py           # commits changes
  python scripts/migrate_deal_details.py --dry-run  # prints changes, no commit
"""

import argparse
import os
import sys

# ── Ensure project root is on sys.path ──────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from modules.database import Session  # noqa: E402
from modules.models import Deal       # noqa: E402

# Field renames: (old_key, new_key)
RENAMES = [
    ("percent",               "discount_percent"),
    ("minimum_order_value",   "spend_min"),
    ("points_multiplier",     "earn_multiplier"),
    ("applicable_categories", "scope_categories"),
]


def migrate(dry_run: bool = False) -> None:
    session = Session()
    updated_count = 0
    skipped_count = 0

    try:
        deals = session.query(Deal).all()

        for deal in deals:
            details = deal.deal_details
            if not isinstance(details, dict):
                skipped_count += 1
                continue

            changes: list[tuple[str, str]] = []
            new_details = dict(details)

            for old_key, new_key in RENAMES:
                if old_key in new_details:
                    new_details[new_key] = new_details.pop(old_key)
                    changes.append((old_key, new_key))

            if not changes:
                skipped_count += 1
                continue

            # Report what would change / was changed
            change_summary = ", ".join(f'"{o}" → "{n}"' for o, n in changes)
            print(f"  Deal id={deal.id!r} title={deal.title!r}: {change_summary}")

            if not dry_run:
                deal.deal_details = new_details
                # Explicitly flag the JSON column as modified so SQLAlchemy
                # detects the change (required for mutable JSON columns).
                from sqlalchemy.orm.attributes import flag_modified
                flag_modified(deal, "deal_details")

            updated_count += 1

        if dry_run:
            print(f"\n[DRY RUN] Would update {updated_count} deal(s), skip {skipped_count} deal(s). No changes committed.")
            session.rollback()
        else:
            session.commit()
            print(f"\nMigration complete: updated {updated_count} deal(s), skipped {skipped_count} deal(s).")

    except Exception as exc:
        session.rollback()
        print(f"\nERROR — transaction rolled back: {exc}", file=sys.stderr)
        raise
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate deal_details field names to unified schema.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes without committing them to the database.",
    )
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
