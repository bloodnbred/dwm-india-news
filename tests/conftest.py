"""Shared pytest fixtures.

Tests never touch the real warehouse or data/raw. Every fixture writes to a
tmp_path so the suite is safe to run at any time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dwm.config import Settings

TOI_FIXTURE = """publish_date,headline_category,headline_text
20010101,sports.wwe,"win over cena satisfying but defeating undertaker bigger roman reigns"
20010102,unknown,"Status quo will not be disturbed at Ayodhya; says Vajpayee"
20010102,unknown,"Fissures in Hurriyat over Pak visit"
20010103,business.gadgets,"New phone launch promises faster charging and better camera"
20010104,politics.parliament,"Parliament clears bill after heated debate!!!"
20010105,sports.cricket,"India win by 5 wickets in the final over"
"""

IFND_FIXTURE = """id,Statement,Image,Web,Category,Date,Label
1,"WHO praises India's Aarogya Setu app",https://example.com/a.jpg,DNAINDIA,COVID-19,Oct-20,TRUE
2,"Bihar Assembly Election 2020: Tej Pratap shifted",https://example.com/b.jpg,DNAINDIA,ELECTION,Nov 2020,TRUE
3,"Fact Check: 1938 video shared as PM performing yoga",https://example.com/c.jpg,INDIA TODAY,VIOLENCE,Oct-20,Fake
"""

NIFTY_FIXTURE = """Date,Open,High,Low,Close,Volume,Turnover
01-Jan-15,8272.8,8294.7,8248.75,8284,56560411,2321.88
02-Jan-15,8288.7,8410.6,8288.7,8395.45,101887024,4715.72
05-Jan-15,8407.95,8445.6,8363.9,8378.4,118160545,5525.52
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "test.duckdb", years=5, chunk=1000)


@pytest.fixture
def toi_csv(tmp_path: Path) -> Path:
    path = tmp_path / "india-news-headlines.csv"
    path.write_text(TOI_FIXTURE, encoding="utf-8")
    return path


@pytest.fixture
def ifnd_csv(tmp_path: Path) -> Path:
    path = tmp_path / "IFND.csv"
    path.write_text(IFND_FIXTURE, encoding="utf-8")
    return path


@pytest.fixture
def nifty_csv(tmp_path: Path) -> Path:
    path = tmp_path / "nifty50.csv"
    path.write_text(NIFTY_FIXTURE, encoding="utf-8")
    return path


@pytest.fixture
def con(settings: Settings):
    from dwm.db import connect

    connection = connect(settings)
    try:
        yield connection
    finally:
        connection.close()
