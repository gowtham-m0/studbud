from pathlib import Path

import pytest

from studbud_backend.storage import LocalStorage


@pytest.mark.asyncio
async def test_local_storage_prefix_cleanup(tmp_path: Path) -> None:
    storage = LocalStorage(tmp_path)

    await storage.save_bytes("documents/u1/assets/d1/page-1.jpg", b"page")
    await storage.save_bytes("documents/u1/assets/d1/figure-1-1.png", b"figure")
    await storage.save_bytes("documents/u2/assets/d2/page-1.jpg", b"other")

    keys = await storage.list_keys("documents/u1/")
    assert set(keys) == {
        "documents/u1/assets/d1/page-1.jpg",
        "documents/u1/assets/d1/figure-1-1.png",
    }

    removed = await storage.delete_prefix("documents/u1/assets/d1/")
    assert removed == 2
    assert await storage.list_keys("documents/u1/") == []
    assert await storage.list_keys("documents/u2/") == ["documents/u2/assets/d2/page-1.jpg"]

    with pytest.raises(ValueError):
        await storage.delete_prefix("")
