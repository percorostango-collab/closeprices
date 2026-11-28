import os
from dataclasses import dataclass, field


def _f(name, default):
    return type(default)(os.environ.get(name, default))


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.environ.get("PV_DB", "var/prezzi_vicini.db"))
    turso_url: str = field(default_factory=lambda: os.environ.get("PV_TURSO_URL", ""))
    turso_token: str = field(default_factory=lambda: os.environ.get("PV_TURSO_TOKEN", ""))
    serpapi_key: str = field(default_factory=lambda: os.environ.get("PV_SERPAPI_KEY", ""))
    serpapi_base: str = field(default_factory=lambda: os.environ.get("PV_SERPAPI_BASE", "https://serpapi.com"))
    shopping_monthly_limit: int = field(default_factory=lambda: _f("PV_SHOPPING_MONTHLY_LIMIT", 200))
    offers_ttl_days: float = field(default_factory=lambda: _f("PV_OFFERS_TTL_DAYS", 3.0))
    offers_empty_ttl_days: float = field(default_factory=lambda: _f("PV_OFFERS_EMPTY_TTL_DAYS", 1.0))
    offers_timeout_s: float = field(default_factory=lambda: _f("PV_OFFERS_TIMEOUT_S", 12.0))
    omni_url: str = field(default_factory=lambda: os.environ.get("PV_OMNIROUTE_URL", "").strip())
    omni_key: str = field(default_factory=lambda: os.environ.get("PV_OMNIROUTE_KEY", "").strip())
    llm_model: str = field(default_factory=lambda: os.environ.get("PV_LLM_MODEL", "").strip())
    search_provider: str = field(default_factory=lambda: os.environ.get("PV_SEARCH_PROVIDER", "").strip())
    fetch_provider: str = field(default_factory=lambda: os.environ.get("PV_FETCH_PROVIDER", "").strip())
    discovery_budget_s: float = field(default_factory=lambda: _f("PV_DISCOVERY_BUDGET_S", 25.0))
    discovery_ttl_days: float = field(default_factory=lambda: _f("PV_DISCOVERY_TTL_DAYS", 7.0))
    discovery_max_candidates: int = field(default_factory=lambda: _f("PV_DISCOVERY_MAX_CANDIDATES", 10))
    discovery_llm_calls: int = field(default_factory=lambda: _f("PV_DISCOVERY_LLM_CALLS", 6))
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
    def product_sources(self):
        """Banche dati aperte del progetto Open Food Facts: se un codice non è nel cibo può essere in cosmetici,
        cibo per animali o altri prodotti. Con un indirizzo di prova (test) si usa quello soltanto."""
        b = self.off_base.rstrip("/")
        if b.endswith("world.openfoodfacts.org"):
            return [("Open Food Facts", b), ("Open Beauty Facts", b.replace("openfoodfacts", "openbeautyfacts")),
                    ("Open Pet Food Facts", b.replace("openfoodfacts", "openpetfoodfacts")),
                    ("Open Products Facts", b.replace("openfoodfacts", "openproductsfacts"))]
        return [("Open Food Facts", b)]

    @property
    def omni_enabled(self) -> bool:
        return bool(self.omni_url and self.omni_key)

    @property
    def user_agent(self) -> str:
        return f"PrezziVicini/1.0 (+{self.contact})"

    @property
    def use_turso(self) -> bool:
        return bool(self.turso_url and self.turso_token)
