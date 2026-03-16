from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_name: str
    database_url: str
    log_level: str
    headless: bool
    softbank_sid: str
    softbank_password: str
    softbank_login_url: str
    softbank_target_url: str
    hepco_login_id: str
    hepco_password: str
    hepco_login_url: str
    hepco_target_url: str
    mitsuuroko_login_id: str
    mitsuuroko_password: str
    mitsuuroko_login_url: str
    mitsuuroko_gas_usage_url: str
    mitsuuroko_gas_charge_url: str
    logs_dir: Path
    snapshots_dir: Path
    data_dir: Path


def _to_bool(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache
def get_settings() -> Settings:
    logs_dir = BASE_DIR / "logs"
    snapshots_dir = BASE_DIR / "snapshots"
    data_dir = BASE_DIR / "data"
    logs_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        app_name="home-utility-api",
        database_url=os.getenv("DATABASE_URL", "sqlite:///./data/home_utility.db"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        headless=_to_bool(os.getenv("HEADLESS"), default=True),
        softbank_sid=os.getenv("SOFTBANK_SID", ""),
        softbank_password=os.getenv("SOFTBANK_PASSWORD", ""),
        softbank_login_url=os.getenv(
            "SOFTBANK_LOGIN_URL",
            "https://bbss.softbankbb.co.jp/AUT/ftth?mem=memCertAFsd&.func=myPage",
        ),
        softbank_target_url=os.getenv("SOFTBANK_TARGET_URL", ""),
        hepco_login_id=os.getenv("HEPCO_LOGIN_ID", ""),
        hepco_password=os.getenv("HEPCO_PASSWORD", ""),
        hepco_login_url=os.getenv("HEPCO_LOGIN_URL", "https://www.epower-portal.com/hepco"),
        hepco_target_url=os.getenv(
            "HEPCO_TARGET_URL",
            "https://www.epower-portal.com/hepco/mypage/usages/billinginfo/",
        ),
        mitsuuroko_login_id=os.getenv("MITSUUROKO_LOGIN_ID", ""),
        mitsuuroko_password=os.getenv("MITSUUROKO_PASSWORD", ""),
        mitsuuroko_login_url=os.getenv(
            "MITSUUROKO_LOGIN_URL",
            "https://mitsuurokogroup-enecheck.com/login.php",
        ),
        mitsuuroko_gas_usage_url=os.getenv(
            "MITSUUROKO_GAS_USAGE_URL",
            "https://mitsuurokogroup-enecheck.com/gas.php?mode=consumption",
        ),
        mitsuuroko_gas_charge_url=os.getenv(
            "MITSUUROKO_GAS_CHARGE_URL",
            "https://mitsuurokogroup-enecheck.com/gas.php?mode=charge",
        ),
        logs_dir=logs_dir,
        snapshots_dir=snapshots_dir,
        data_dir=data_dir,
    )
