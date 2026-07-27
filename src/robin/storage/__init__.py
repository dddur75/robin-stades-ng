"""Shared SQLAlchemy metadata and transactional persistence."""

from robin.storage import prospective_models as prospective_models
from robin.storage.models import Base

__all__ = ["Base", "prospective_models"]
