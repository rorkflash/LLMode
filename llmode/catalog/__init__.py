"""Model catalog package.

Provides :class:`~llmode.catalog.huggingface.CatalogService` for searching the
Hugging Face Hub, downloading weights into the local model store, and recording
manifests in the database.
"""

from llmode.catalog.huggingface import CatalogService

__all__ = ["CatalogService"]
