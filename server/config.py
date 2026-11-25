import os
from dataclasses import dataclass, field


def _f(name, default):
    return type(default)(os.environ.get(name, default))


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("PV_DB", "var/prezzi_vicini.db"))
    turso_url: str = field(default_factory=lambda: os.environ.get("PV_TURSO_URL", ""))
    turso_token: str = field(default_factory=lambda: os.environ.get("PV_TURSO_TOKEN", ""))
    turso_pipeline: str = field(default_factory=lambda: os.environ.get("PV_TURSO_PIPELINE", "v2"))
    contact: str = field(default_factory=lambda: os.environ.get("PV_CONTACT", "contatto-non-configurato"))
    off_base: str = field(default_factory=lambda: os.environ.get("OFF_BASE", "https://world.openfoodfacts.org"))
    index_budget_s: float = field(default_factory=lambda: _f("PV_INDEX_BUDGET_S", 8.0))
    catalog_ttl_days: int = field(default_factory=lambda: _f("PV_CATALOG_TTL_DAYS", 30))
    product_ttl_days: int = field(default_factory=lambda: _f("PV_PRODUCT_TTL_DAYS", 30))
    notfound_ttl_days: int = field(default_factory=lambda: _f("PV_NOTFOUND_TTL_DAYS", 7))
    correction_min_users: int = field(default_factory=lambda: _f("PV_CORRECTION_MIN_USERS", 3))
    max_radius_km: float = 30.0
    default_radius_km: float = 10.0
    request_interval_s: float = field(default_factory=lambda: _f("PV_REQUEST_INTERVAL_S", 1.5))

    @property
    def user_agent(self) -> str:
        return f"PrezziVicini/1.0 (+{self.contact})"

    @property
    def use_turso(self) -> bool:
        return bool(self.turso_url and self.turso_token)
