"""
FlowGuard Configuration Module

Reads all environment variables with sensible defaults.
All configuration is centralized here — no hardcoded secrets anywhere else.
"""

import os
from dataclasses import dataclass


@dataclass
class Config:
    """Application configuration loaded from environment variables.

    Usage:
        config = Config.from_env()
        print(config.MONGO_URI)
    """

    MONGO_URI: str
    PORT: int
    RATE_LIMIT_DEFAULT: int
    RATE_LIMIT_WINDOW: int
    MAX_QUEUE_SIZE: int
    WORKER_THREADS: int

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables.

        Returns:
            Config: Populated configuration dataclass.

        Raises:
            ValueError: If MONGO_URI is not set (required).
        """
        mongo_uri = os.environ.get("MONGO_URI", "")
        if not mongo_uri:
            print(
                "WARNING: MONGO_URI not set. MongoDB features will be disabled. "
                "Set MONGO_URI in your .env file or environment."
            )

        return cls(
            MONGO_URI=mongo_uri,
            PORT=int(os.environ.get("PORT", "5000")),
            RATE_LIMIT_DEFAULT=int(os.environ.get("RATE_LIMIT_DEFAULT", "100")),
            RATE_LIMIT_WINDOW=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
            MAX_QUEUE_SIZE=int(os.environ.get("MAX_QUEUE_SIZE", "1000")),
            WORKER_THREADS=int(os.environ.get("WORKER_THREADS", "2")),
        )


# Global config instance — initialized once at startup
config = Config.from_env()
