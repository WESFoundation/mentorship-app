"""One-time script to fix and canonicalize mentor locations on the live server (PostgreSQL or SQLite).

Resolves each mentor's country, state, and city into structured columns:
- Cleans and deduplicates contradictory entries (e.g. 'Luxembourg, Pakistan' -> Luxembourg)
- Infers canonical state/province and city based on official platform location cascade
- Updates structured columns: mentor_profile.country, mentor_profile.state, mentor_profile.city, mentor_profile.location

Usage:
  # Dry run (safe inspection):
  python fix_mentor_locations_live.py

  # Apply changes directly to connected database:
  python fix_mentor_locations_live.py --apply
"""
import sys
import os

APP_ROOT = os.path.abspath(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_ROOT)

from app import app, db, User, MentorProfile, resolve_location


def main():
    apply_changes = "--apply" in sys.argv
    print("=" * 78)
    print("LIVE SERVER MENTOR LOCATION FIX SCRIPT")
    print("MODE: " + ("APPLY (Writing changes to database)" if apply_changes else "DRY RUN (Pass --apply to write)"))
    print("=" * 78)

    with app.app_context():
        # Ensure database tables and columns exist
        db.create_all()

        mentors = (
            db.session.query(User, MentorProfile)
            .join(MentorProfile, MentorProfile.user_id == User.id)
            .filter(User.user_type == "1")
            .order_by(User.id)
            .all()
        )
        print(f"Total mentors found: {len(mentors)}\n")

        changed = []
        for user, profile in mentors:
            before = (
                profile.location or "",
                profile.country or "",
                profile.state or "",
                profile.city or ""
            )
            resolved = resolve_location(
                country=profile.country,
                state=profile.state,
                city=profile.city,
                legacy_location=profile.location
            )
            after = (
                resolved["location"] or "",
                resolved["country"] or "",
                resolved["state"] or "",
                resolved["city"] or ""
            )

            if before != after:
                changed.append((user, profile, before, after, resolved.get("notes", [])))

        print(f"Profiles requiring location update / standardization: {len(changed)}")
        for user, profile, before, after, notes in changed:
            print(f"\n[User {user.id}] {user.name} <{user.email}>")
            print(f"  Before -> loc: {before[0]!r} | country: {before[1]!r} | state: {before[2]!r} | city: {before[3]!r}")
            print(f"  After  -> loc: {after[0]!r} | country: {after[1]!r} | state: {after[2]!r} | city: {after[3]!r}")
            if notes:
                print(f"  Notes  -> {', '.join(notes)}")

        if apply_changes and changed:
            for user, profile, before, after, notes in changed:
                profile.location = after[0] or None
                profile.country = after[1] or None
                profile.state = after[2] or None
                profile.city = after[3] or None
            try:
                db.session.commit()
                print(f"\n✅ Successfully committed {len(changed)} updated mentor location(s) to database.")
            except Exception as e:
                db.session.rollback()
                print(f"\n❌ ERROR committing to database: {e}")
                sys.exit(1)
        elif not apply_changes and changed:
            print(f"\nℹ️ Dry run completed. Re-run with '--apply' to persist these {len(changed)} updates.")
        else:
            print("\n✅ All mentor locations are already properly standardized.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
