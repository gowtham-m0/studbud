from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import anyio
import boto3

from .config import get_settings

logger = logging.getLogger(__name__)


class Storage(Protocol):
    async def save(self, key: str, source_path: Path) -> None: ...
    async def save_bytes(self, key: str, data: bytes) -> None: ...
    async def read_bytes(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> int: ...
    async def list_keys(self, prefix: str) -> list[str]: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        resolved = (self.root / key).resolve()
        if self.root.resolve() not in resolved.parents:
            raise ValueError("Invalid storage key.")
        return resolved

    async def save(self, key: str, source_path: Path) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(lambda: destination.write_bytes(source_path.read_bytes()))

    async def save_bytes(self, key: str, data: bytes) -> None:
        destination = self._path(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        await anyio.to_thread.run_sync(lambda: destination.write_bytes(data))

    async def read_bytes(self, key: str) -> bytes:
        return await anyio.to_thread.run_sync(lambda: self._path(key).read_bytes())

    async def delete(self, key: str) -> None:
        path = self._path(key)
        await anyio.to_thread.run_sync(lambda: path.unlink(missing_ok=True))

    def _prefix_path(self, prefix: str) -> Path:
        if not prefix.strip():
            raise ValueError("Storage prefix must not be empty.")
        candidate = (self.root / prefix).resolve()
        if candidate != self.root.resolve() and self.root.resolve() not in candidate.parents:
            raise ValueError("Invalid storage prefix.")
        return candidate

    async def delete_prefix(self, prefix: str) -> int:
        def _delete() -> int:
            target = self._prefix_path(prefix)
            if not target.exists():
                return 0
            files = [target] if target.is_file() else [p for p in target.rglob("*") if p.is_file()]
            for file in files:
                file.unlink(missing_ok=True)
            for directory in sorted((p for p in target.rglob("*") if p.is_dir()), reverse=True):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            if target.is_dir():
                try:
                    target.rmdir()
                except OSError:
                    pass
            return len(files)

        return await anyio.to_thread.run_sync(_delete)

    async def list_keys(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            target = self._prefix_path(prefix)
            candidates = [target] if target.is_file() else list(target.rglob("*"))
            return [path.relative_to(self.root).as_posix() for path in candidates if path.is_file()]

        return await anyio.to_thread.run_sync(_list)


class R2Storage:
    def __init__(self) -> None:
        settings = get_settings()
        if not all(
            [
                settings.r2_endpoint,
                settings.r2_bucket,
                settings.r2_access_key_id,
                settings.r2_secret_access_key,
            ]
        ):
            raise RuntimeError("R2 storage is selected but credentials are incomplete.")
        self.bucket = settings.r2_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )

    async def save(self, key: str, source_path: Path) -> None:
        await anyio.to_thread.run_sync(
            lambda: self.client.upload_file(
                str(source_path),
                self.bucket,
                key,
                ExtraArgs={"ContentType": "application/pdf"},
            )
        )

    async def save_bytes(self, key: str, data: bytes) -> None:
        await anyio.to_thread.run_sync(
            lambda: self.client.put_object(Bucket=self.bucket, Key=key, Body=data)
        )

    async def read_bytes(self, key: str) -> bytes:
        def _read() -> bytes:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()

        return await anyio.to_thread.run_sync(_read)

    async def delete(self, key: str) -> None:
        await anyio.to_thread.run_sync(
            lambda: self.client.delete_object(Bucket=self.bucket, Key=key)
        )

    async def delete_prefix(self, prefix: str) -> int:
        def _delete() -> int:
            paginator = self.client.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys.extend(item["Key"] for item in page.get("Contents", []))
            for start in range(0, len(keys), 1000):
                batch = keys[start : start + 1000]
                if batch:
                    self.client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": [{"Key": key} for key in batch]},
                    )
            return len(keys)

        return await anyio.to_thread.run_sync(_delete)

    async def list_keys(self, prefix: str) -> list[str]:
        def _list() -> list[str]:
            paginator = self.client.get_paginator("list_objects_v2")
            keys: list[str] = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys.extend(item["Key"] for item in page.get("Contents", []))
            return keys

        return await anyio.to_thread.run_sync(_list)


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    backend = settings.storage_backend.lower()
    if backend == "r2":
        return R2Storage()
    if backend == "auto" and settings.r2_endpoint and settings.r2_bucket:
        return R2Storage()
    if backend == "r2":
        raise RuntimeError("R2 selected but R2_ENDPOINT/R2_BUCKET are missing.")
    logger.info("Using local filesystem storage at %s", settings.storage_dir)
    return LocalStorage(Path(settings.storage_dir))
