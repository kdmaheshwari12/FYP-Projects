# app/db/mongodb.py
"""
Compatibility shim: all legacy routes import from `app.db.mongodb`.
This module re-exports everything from `app.database.mongodb` and adds
the extra collections that the legacy routes expect.
"""

from app.database.mongodb import (
    get_database,
    get_collection,
    connect_to_mongo,
    close_mongo_connection,
)

# ── Core user collection (re-exported as a direct Motor collection) ──────────
# Legacy routes used `users_collection` as a direct Motor collection object,
# NOT as a callable lambda. We expose a lazy proxy so it resolves after startup.

class _LazyCollection:
    """
    Proxy that looks up the collection from the live DB instance each time
    an attribute or method is called. This is needed because at import time
    the DB connection is not yet established.
    """
    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, item):
        col = get_collection(self._name)
        return getattr(col, item)

    def __call__(self, *args, **kwargs):
        return get_collection(self._name)(*args, **kwargs)


# Collections used by legacy routes
users_collection                 = _LazyCollection("users")
itineraries_collection           = _LazyCollection("itineraries")
preferences_collection           = _LazyCollection("preferences")
messages_collection              = _LazyCollection("messages")
broker_collection                = _LazyCollection("brokers")
broker_itineraries_collection    = _LazyCollection("broker_itineraries")
trips_collection                 = _LazyCollection("trips")
broker_reviews_collection        = _LazyCollection("broker_reviews")
weather_collection               = _LazyCollection("weather")
