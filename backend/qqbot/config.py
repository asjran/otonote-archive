from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class Config:
    app_id: str
    secret: str = field(repr=False)
    bundle: Path
    state: Path
    public_base_url: str
    font: str | None = None
    api_base_url: str = "https://api.bot.qq.com"
    max_pending: int = 200
    data_url: str | None = None
    refresh_seconds: int = 600

    def __post_init__(self):
        if not self.app_id.isdigit() or not self.secret:
            raise ValueError("QQ AppID and AppSecret are required")
        url = urlparse(self.public_base_url)
        if (url.scheme != "https" or not url.hostname or url.path not in ("", "/")
                or url.username or url.password or url.query or url.fragment):
            raise ValueError("OURNOTES_QQ_PUBLIC_BASE_URL must be an HTTPS origin")
        if self.api_base_url not in ("https://api.bot.qq.com", "https://api.sgroup.qq.com", "https://sandbox.api.sgroup.qq.com"):
            raise ValueError("use an official QQ API origin")
        if self.data_url:
            data = urlparse(self.data_url)
            if data.scheme != "https" or not data.hostname or data.username or data.password or data.query or data.fragment:
                raise ValueError("website data source must be HTTPS")
        if self.refresh_seconds < 60:
            raise ValueError("refresh interval must be at least 60 seconds")
        if not 1 <= self.max_pending <= 1000:
            raise ValueError("max_pending must be 1..1000")

    @classmethod
    def from_env(cls):
        env = os.environ
        return cls(env["OURNOTES_QQ_APP_ID"], env["OURNOTES_QQ_APP_SECRET"],
                   Path(env.get("OURNOTES_QQ_BUNDLE", "/content")), Path(env["OURNOTES_QQ_STATE"]),
                   env["OURNOTES_QQ_PUBLIC_BASE_URL"].rstrip("/"), env.get("OURNOTES_QQ_FONT"),
                   env.get("OURNOTES_QQ_API_BASE_URL", "https://api.bot.qq.com"),
                   data_url=env.get("OURNOTES_QQ_DATA_URL"), refresh_seconds=int(env.get("OURNOTES_QQ_REFRESH_SECONDS", "600")))
