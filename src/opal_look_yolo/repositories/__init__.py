"""Per-aggregate repositories sharing one connection and the
Store.write_txn unit of work."""

from .meta import MetaRepository, SqliteMetaRepository, new_revision
from .personas import PersonaRepository, SqlitePersonaRepository
from .profiles import ProfileRepository, SqliteProfileRepository
from .settings import SettingsRepository, SqliteSettingsRepository

__all__ = [
    "MetaRepository",
    "PersonaRepository",
    "ProfileRepository",
    "SettingsRepository",
    "SqliteMetaRepository",
    "SqlitePersonaRepository",
    "SqliteProfileRepository",
    "SqliteSettingsRepository",
    "new_revision",
]
