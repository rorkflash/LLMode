"""Hugging Face Hub catalog source: search, download, manifest.

We use ``huggingface_hub`` for both discovery and downloads. Format is inferred
from filenames so we can tell which backend will be able to run a model. All
network calls are wrapped defensively — discovery should degrade, not crash, if
the Hub is unreachable.
"""

from __future__ import annotations

from pathlib import Path

from huggingface_hub import HfApi, hf_hub_download, snapshot_download

from llmode.schemas import ModelFormat, ModelManifest
from llmode.store import Database


def _infer_format(filename: str) -> ModelFormat:
    """Guess a model's weight format from a representative filename."""
    lower = filename.lower()
    if lower.endswith(".gguf"):
        return ModelFormat.GGUF
    if lower.endswith(".safetensors"):
        return ModelFormat.SAFETENSORS
    if "mlx" in lower:
        return ModelFormat.MLX
    return ModelFormat.UNKNOWN


class CatalogService:
    """High-level operations over the remote catalog + local model store."""

    def __init__(self, db: Database, models_dir: Path) -> None:
        """Wire the service to the persistence layer and the weights directory."""
        self._db = db
        self._models_dir = models_dir
        self._api = HfApi()

    def search(self, query: str, limit: int = 20) -> list[ModelManifest]:
        """Search the Hub and return lightweight (not-yet-downloaded) manifests.

        We only populate metadata we can get cheaply from the listing; ``path``
        stays None because nothing is on disk yet. Failures return an empty list.
        """
        try:
            results = self._api.list_models(search=query, limit=limit, sort="downloads")
        except Exception:  # noqa: BLE001 — network/Hub errors must not crash search
            return []

        manifests: list[ModelManifest] = []
        for m in results:
            # ``m.id`` is the repo id, e.g. 'TheBloke/Llama-2-7B-GGUF'. We can't
            # know the exact file/quant without a deeper query, so format stays
            # inferred from the repo name as a hint.
            manifests.append(
                ModelManifest(
                    id=m.id,
                    name=m.id.split("/")[-1],
                    source="huggingface",
                    format=_infer_format(m.id),
                )
            )
        return manifests

    def download(self, repo_id: str, filename: str | None = None) -> ModelManifest:
        """Download a model into the local store and persist its manifest.

        Two modes:
          * ``filename`` given  -> fetch a single file (typical for GGUF quants).
          * ``filename`` None   -> snapshot the whole repo (safetensors/MLX dirs).

        Returns the persisted local manifest with ``path`` and ``size_bytes`` set.
        """
        target_dir = self._models_dir / repo_id.replace("/", "__")

        if filename:
            # Single-file download (e.g. one GGUF quantization).
            local_path = Path(
                hf_hub_download(
                    repo_id=repo_id, filename=filename, local_dir=target_dir
                )
            )
            fmt = _infer_format(filename)
            size = local_path.stat().st_size
            manifest_id = f"{repo_id}:{filename}"
        else:
            # Full-repo snapshot (directory of weights).
            local_path = Path(snapshot_download(repo_id=repo_id, local_dir=target_dir))
            fmt = self._infer_repo_format(repo_id, local_path)
            size = self._dir_size(local_path)
            manifest_id = repo_id

        manifest = ModelManifest(
            id=manifest_id,
            name=repo_id.split("/")[-1],
            source="huggingface",
            format=fmt,
            size_bytes=size,
            path=str(local_path),
            backends=self._compatible_backends(fmt),
        )
        # Persist so the model shows up as a local/available entry immediately.
        self._db.upsert_model(manifest)
        self._db.add_event("download", f"Downloaded {manifest_id}", manifest_id)
        return manifest

    @staticmethod
    def _infer_repo_format(repo_id: str, directory: Path) -> ModelFormat:
        """Infer a downloaded repo's format, using the repo id as a hint.

        MLX models ship as ``.safetensors`` too, so file extensions alone cannot
        distinguish them from vLLM/transformers checkpoints. We treat repos whose
        id mentions 'mlx' (e.g. the ``mlx-community`` org) as MLX, and otherwise
        fall back to scanning the files on disk.
        """
        if "mlx" in repo_id.lower():
            return ModelFormat.MLX
        return CatalogService._infer_dir_format(directory)

    @staticmethod
    def _infer_dir_format(directory: Path) -> ModelFormat:
        """Infer format for a downloaded repo directory by scanning its files."""
        names = [p.name for p in directory.rglob("*") if p.is_file()]
        for n in names:
            fmt = _infer_format(n)
            if fmt != ModelFormat.UNKNOWN:
                return fmt
        return ModelFormat.UNKNOWN

    @staticmethod
    def _dir_size(directory: Path) -> int:
        """Sum the byte size of every file under a directory."""
        return sum(p.stat().st_size for p in directory.rglob("*") if p.is_file())

    @staticmethod
    def _compatible_backends(fmt: ModelFormat) -> list[str]:
        """Map a weight format to the backend names that can run it."""
        mapping = {
            ModelFormat.GGUF: ["llama.cpp", "ollama"],
            ModelFormat.MLX: ["mlx"],
            ModelFormat.SAFETENSORS: ["vllm"],
        }
        return mapping.get(fmt, [])
