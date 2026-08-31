import os
import re
from pathlib import Path
from textwrap import dedent

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "sql"

load_dotenv(REPO_ROOT / ".env")


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            dedent(
                f"""
                Missing required environment variable {name!r}.
                """
            ).strip()
        )
    return value


def _validate_database_url(url: str) -> None:
    match = re.match(r"^postgres(?:ql)?://[^:]+:([^@]*)@", url)
    if not match:
        raise RuntimeError(
            "DATABASE_URL is not a postgresql://user:password@host:port/db URL."
        )

    password = match.group(1)
    
    unsafe = sorted(set(password) & set("@/?#[] "))
    if unsafe:
        chars = " ".join(repr(c) for c in unsafe)
        raise RuntimeError(
            dedent(
                f"""
                The password in DATABASE_URL contains {chars}, which must be
                percent-encoded inside a URL (@ -> %40, / -> %2F, # -> %23,
                ? -> %3F, space -> %20).
                """
            ).strip()
        )


DATABASE_URL = _required("DATABASE_URL")
_validate_database_url(DATABASE_URL)

ORDERS_API_URL = os.getenv(
    "ORDERS_API_URL",
    "https://jzozteoirwfczccltcdr.supabase.co/rest/v1/orders_raw",
)
ORDERS_API_KEY = os.getenv(
    "ORDERS_API_KEY",
    "sb_publishable_Xwjiw--qkKcbMuSbKd6I2w_wN9mpNTv",
)

FX_API_URL = os.getenv("FX_API_URL", "https://api.frankfurter.dev/v1")

FX_BASE_CURRENCY = "EUR"
FX_QUOTE_CURRENCIES = ["RON"]
