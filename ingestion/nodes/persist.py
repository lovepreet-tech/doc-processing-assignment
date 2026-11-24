"""Commits the session, finalizing the writes made by the parse/graph nodes above."""


def persist(db) -> None:
    db.commit()
