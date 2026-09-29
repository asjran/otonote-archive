"""OurNotes Dynamic Query Service deep modules.

首期实现包含 Dataset Query Module、Binding Module、Health Module 及其支撑
契约；不依赖 FastAPI、SQLite 或 ``tools.resource_pipeline.release_repository``，
以确保可以单独测试和复用。
"""

from __future__ import annotations