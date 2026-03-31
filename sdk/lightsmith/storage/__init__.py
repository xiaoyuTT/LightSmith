"""storage 子包 — P0.4 本地 SQLite 写入器。"""

from lightsmith.storage.sqlite import RunWriter, get_default_writer

__all__ = ["RunWriter", "get_default_writer"]
