"""Fixed parameters from section 3 of the Stage 1 brief, and repository paths."""
from pathlib import Path

#: Repository root: src/overton/settings.py -> parents[2].
ROOT = Path(__file__).resolve().parents[2]

API_BASE = "https://api.openalex.org"
API_KEY_ENV = "OPENALEX_API_KEY"

YEARS = range(2016, 2026)          # 2016-2025 inclusive, OpenAlex publication_year
PILOT_JOURNALS = ("aer", "qje")
PILOT_YEARS = range(2019, 2021)

PER_PAGE = 100
TIMEOUT = 30                       # seconds
BACKOFF = (1, 2, 4, 8, 16)         # seconds; one entry per retry
MAX_REQUESTS_PER_SECOND = 5
REQUEST_BUDGET = 5000              # stop if the full-harvest estimate exceeds this

RETRY_STATUSES = frozenset({429, 403})   # plus every status >= 500
BUDGET_MESSAGE = ("OpenAlex budget or rate limit reached — "
                  "resume after midnight UTC")

DOI_BATCH_SIZE = 25_000
SAMPLE_SEED = 20261012
SAMPLE_SIZE = 50


class Paths:
    """Every file location, relative to a root (the repository, or a tmp dir in tests)."""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self.config = self.root / "config"
        self.journals = self.config / "journals.csv"
        self.journals_resolved = self.config / "journals_resolved.csv"
        self.data = self.root / "data"
        self.raw = self.data / "raw" / "openalex"
        self.interim = self.data / "interim"
        self.release = self.data / "release"
        self.review = self.data / "review"
        self.reports = self.root / "reports"
        self.manifest = self.reports / "harvest_manifest.csv"
        self.harvest_report = self.reports / "harvest_report.csv"
        self.run_report = self.reports / "STAGE1_RUN_REPORT.md"
        self.works = self.interim / "works.csv"
        self.authorships = self.interim / "authorships.csv"
        self.works_filtered = self.interim / "works_filtered.csv"
        self.api_usage = self.interim / "api_usage.jsonl"
        self.estimate = self.interim / "harvest_estimate.csv"

    def jy_dir(self, journal_key: str, year: int) -> Path:
        return self.raw / journal_key / str(year)
