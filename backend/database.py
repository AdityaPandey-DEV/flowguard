"""
FlowGuard Database Module

Handles MongoDB Atlas connection via pymongo.
Uses lazy initialization — the connection is established on first use,
not at import time. This prevents crashes if MongoDB is temporarily unavailable.
"""

from typing import Optional

from pymongo import MongoClient
from pymongo.database import Database
from pymongo.errors import ConnectionFailure

from config import config


class DatabaseManager:
    """Manages MongoDB connection lifecycle.

    Uses lazy initialization: the connection is created on the first call
    to get_db(), not when the class is instantiated. This is important because:
    1. It allows the app to start even if MongoDB is temporarily down.
    2. It avoids unnecessary connections during testing.

    Attributes:
        _client: The pymongo MongoClient instance (None until first use).
        _db: The MongoDB database instance (None until first use).
    """

    def __init__(self) -> None:
        self._client: Optional[MongoClient] = None
        self._db: Optional[Database] = None

    def get_db(self) -> Optional[Database]:
        """Get the MongoDB database instance.

        Creates the connection on first call (lazy initialization).

        Returns:
            Database: The pymongo Database object, or None if MONGO_URI is not set.
        """
        if not config.MONGO_URI:
            return None

        if self._db is None:
            try:
                self._client = MongoClient(
                    config.MONGO_URI,
                    serverSelectionTimeoutMS=5000,
                    connectTimeoutMS=5000,
                )
                # Ping to verify the connection works
                self._client.admin.command("ping")
                self._db = self._client.get_default_database("flowguard")
                print("✅ Connected to MongoDB Atlas")
            except ConnectionFailure as e:
                print(f"⚠️  MongoDB connection failed: {e}")
                print("   App will run without persistence. Data is in-memory only.")
                return None

        return self._db

    def close(self) -> None:
        """Close the MongoDB connection gracefully."""
        if self._client:
            self._client.close()
            self._client = None
            self._db = None
            print("MongoDB connection closed.")

    def is_connected(self) -> bool:
        """Check if MongoDB is currently connected.

        Returns:
            bool: True if connected and responsive.
        """
        if self._client is None:
            return False
        try:
            self._client.admin.command("ping")
            return True
        except ConnectionFailure:
            return False


# Global database manager instance
db_manager = DatabaseManager()
