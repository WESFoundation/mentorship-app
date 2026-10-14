"""Normalise every mentor's location into the structured country / state / city
columns so it matches the profile-completion cascade.

This is the tool for "edit the mentor database ... show proper location ... no
duplicates ... no two mentors with the same city name while some other country is
selected". It is deliberately NOT run automatically: you run it, read the report,
and only then decide to write.

SAFETY
------
* Refuses to run unless DATABASE_URL points at a local SQLite file.
* Dry run by default. Nothing is written unless you pass --apply.
* Never deletes or modifies any other mentor field.

Usage
-----
    # 1. work on a throwaway copy and read the report
    copy instance\\mentors_connect.db %TEMP%\\loc.db
    set DATABASE_URL=sqlite:///%TEMP%\\loc.db      (forward slashes)
    py -3.13 "zextra/python codes/fix_mentor_locations.py"

    # 2. happy with the report? apply it
    py -3.13 "zextra/python codes/fix_mentor_locations.py" --apply
"""
import argparse
import os
import sys

APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

# Refuse BEFORE importing the app: app.py runs auto_migrate_schema() at import
# time, so importing it against a shared database would already write to it.
_DB_URL = (os.environ.get("DATABASE_URL") or "").strip()
_ALLOW_REMOTE = "--allow-remote-db" in sys.argv
if not _DB_URL.startswith("sqlite:") and not _ALLOW_REMOTE:
    print("=" * 78)
    print("REFUSING TO RUN")
    print("=" * 78)
    print("  This script would write to a non-SQLite (shared / production) database:")
    print(f"    {_DB_URL[:90] or '(DATABASE_URL not set - app.py would use its own default)'}")
    print()
    print("  Work on a throwaway copy instead:")
    print("    copy instance\\mentors_connect.db %TEMP%\\loc.db")
    print("    set DATABASE_URL=sqlite:///%TEMP%\\loc.db   (forward slashes)")
    print()
    print("  Only pass --allow-remote-db if you really intend to modify that database.")
    sys.exit(2)

sys.path.insert(0, APP_ROOT)
os.environ.setdefault("PRODUCTION", "false")
# The script adds any missing columns itself, so importing the app must not
# migrate anything behind our back.
if _DB_URL.startswith("sqlite:"):
    os.environ["SKIP_AUTO_MIGRATE"] = "1"

from app import (  # noqa: E402
    app, db, User, MentorProfile, resolve_location, mentor_location_parts,
    find_state_for_city, _find_city_owner,
)


def ensure_columns():
    """Add country / state / city to mentor_profile when they are missing."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if "mentor_profile" not in set(inspector.get_table_names()):
        print("mentor_profile table missing; nothing to do")
        return
    existing = {c["name"] for c in inspector.get_columns("mentor_profile")}
    for name, col_type in (("country", "VARCHAR(100)"),
                           ("state", "VARCHAR(100)"),
                           ("city", "VARCHAR(100)")):
        if name in existing:
            continue
        with db.engine.connect() as conn:
            if db.engine.dialect.name == "postgresql":
                conn.execute(text(f"ALTER TABLE mentor_profile ADD COLUMN IF NOT EXISTS {name} {col_type}"))
                conn.commit()
            else:
                conn.execute(text(f"ALTER TABLE mentor_profile ADD COLUMN {name} {col_type}"))
                conn.commit()
        print(f"  added column mentor_profile.{name}")


def find_duplicates(rows):
    """Duplicate (country, state, city) triples and cross-country city clashes."""
    triples = {}
    by_city = {}
    for r in rows:
        key = (r["country"], r["state"], r["city"])
        triples.setdefault(key, []).append(r)
        if r["city"]:
            by_city.setdefault(r["city"].lower(), set()).add(r["country"])
    dupes = {k: v for k, v in triples.items() if len(v) > 1}
    clashes = {c: v for c, v in by_city.items() if len(v) > 1}
    return dupes, clashes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the changes (default is a dry run)")
    ap.add_argument("--allow-remote-db", action="store_true",
                    help="permit writing to a non-SQLite (shared / production) database")
    args = ap.parse_args()

    print("=" * 78)
    print(f"TARGET DATABASE: {app.config.get('SQLALCHEMY_DATABASE_URI')}")
    print("MODE           : " + ("APPLY" if args.apply else "DRY RUN"))
    print("=" * 78)

    with app.app_context():
        ensure_columns()
        db.session.expire_all()

        mentors = (
            db.session.query(User, MentorProfile)
            .join(MentorProfile, MentorProfile.user_id == User.id)
            .filter(User.user_type == "1")
            .order_by(User.name)
            .all()
        )
        print(f"\nMentors with a profile: {len(mentors)}\n")

        rows, changed = [], []
        for user, profile in mentors:
            before = (profile.location or "", profile.country or "",
                      profile.state or "", profile.city or "")
            resolved = resolve_location(
                country=profile.country, state=profile.state,
                city=profile.city, legacy_location=profile.location)
            after = (resolved["location"], resolved["country"],
                     resolved["state"], resolved["city"])
            rows.append({
                "user": user.name, "email": user.email,
                "country": resolved["country"], "state": resolved["state"],
                "city": resolved["city"], "location": resolved["location"],
            })
            if before != after:
                changed.append((user, profile, before, after, resolved["notes"]))

        if args.apply and changed:
            for _user, profile, _before, after, _notes in changed:
                profile.location, profile.country, profile.state, profile.city = after
            try:
                db.session.commit()
                print(f"\nCommitted {len(changed)} mentor profile(s).")
            except Exception as e:
                db.session.rollback()
                print(f"ERROR committing: {e}")
                return 1
        else:
            db.session.rollback()

        print("\n" + "-" * 78)
        print("CHANGES")
        print("-" * 78)
        if not changed:
            print("  (none - already normalised)")
        for user, _profile, before, after, notes in changed:
            print(f"\n  {user.name}  <{user.email}>")
            print(f"    before: location={before[0]!r} country={before[1]!r} "
                  f"state={before[2]!r} city={before[3]!r}")
            print(f"    after : location={after[0]!r} country={after[1]!r} "
                  f"state={after[2]!r} city={after[3]!r}")
            for note in notes:
                print(f"      - {note}")

        dupes, clashes = find_duplicates(rows)
        print("\n" + "-" * 78)
        print("DUPLICATE (country, state, city) TRIPLES")
        print("-" * 78)
        if not dupes:
            print("  (none)")
        for key, group in sorted(dupes.items()):
            print(f"  {key} -> {len(group)} mentors: " + ", ".join(r["user"] for r in group))

        print("\n" + "-" * 78)
        print("SAME CITY NAME UNDER DIFFERENT COUNTRIES")
        print("-" * 78)
        if not clashes:
            print("  (none)")
        for city, countries in sorted(clashes.items()):
            print(f"  {city!r} -> {sorted(countries)}")
            for r in rows:
                if r["city"].lower() == city:
                    print(f"      {r['user']:<28} {r['country']} / {r['state']} / {r['city']}")

        print("\n" + "-" * 78)
        print("STILL NEEDS A MANUAL DECISION")
        print("-" * 78)
        needs_review = []
        for r in rows:
            if not r["country"]:
                needs_review.append((r, "no country"))
                continue
            if r["city"] and not find_state_for_city(r["country"], r["city"]):
                if _find_city_owner(r["city"]) - {r["country"]}:
                    needs_review.append((r, f"city '{r['city']}' is not listed under {r['country']}"))
                elif not r["state"]:
                    needs_review.append((r, f"city '{r['city']}' has no state"))
        if not needs_review:
            print("  (none)")
        for r, why in needs_review:
            print(f"  {r['user']:<28} {why}   [{r['location'] or 'no location'}]")

        print("\n" + "-" * 78)
        print("FINAL STATE (country | state | city | mentors)")
        print("-" * 78)
        buckets = {}
        for r in rows:
            buckets.setdefault(
                (r["country"] or "(none)", r["state"] or "-", r["city"] or "-"), []
            ).append(r["user"])
        for key in sorted(buckets):
            print(f"  {key[0]:<22} {key[1]:<22} {key[2]:<26} {len(buckets[key])}")

        print()
        print("DRY RUN - re-run with --apply to write these changes." if not args.apply
              else "Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())