# -*- coding: utf-8 -*-
"""경쟁사 광고 아카이브 - SQLite 저장소"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "archive.db"
MEDIA_DIR = ROOT / "media"

SCHEMA = """
CREATE TABLE IF NOT EXISTS ads (
    ad_archive_id TEXT PRIMARY KEY,
    page_id       TEXT,
    page_name     TEXT,
    brand         TEXT,
    keyword       TEXT,
    is_active     INTEGER,
    start_date    TEXT,
    end_date      TEXT,
    platforms     TEXT,
    body          TEXT,
    title         TEXT,
    caption       TEXT,
    cta_text      TEXT,
    link_url      TEXT,
    media_type    TEXT,
    first_seen    TEXT,
    last_seen     TEXT,
    raw           TEXT
);
CREATE INDEX IF NOT EXISTS idx_ads_brand ON ads(brand);
CREATE INDEX IF NOT EXISTS idx_ads_first_seen ON ads(first_seen);
CREATE INDEX IF NOT EXISTS idx_ads_start ON ads(start_date);

CREATE TABLE IF NOT EXISTS media (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ad_archive_id TEXT NOT NULL,
    kind          TEXT,
    url           TEXT,
    url_key       TEXT,
    local_path    TEXT,
    thumb_path    TEXT,
    UNIQUE(ad_archive_id, url)
);
CREATE INDEX IF NOT EXISTS idx_media_ad ON media(ad_archive_id);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT,
    ended_at   TEXT,
    brand      TEXT,
    keyword    TEXT,
    found      INTEGER DEFAULT 0,
    new_count  INTEGER DEFAULT 0,
    note       TEXT
);
"""


def media_key(url):
    """fbcdn URL 은 접근할 때마다 서명 쿼리스트링이 바뀐다.
    쿼리스트링을 떼어낸 경로가 같으면 같은 소재이므로, 이것을 중복 판정 키로 쓴다."""
    return (url or "").split("?", 1)[0]


def connect():
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    _migrate(con)
    return con


def _migrate(con):
    cols = [r["name"] for r in con.execute("PRAGMA table_info(media)")]
    if "url_key" not in cols:
        con.execute("ALTER TABLE media ADD COLUMN url_key TEXT")
    for r in con.execute(
            "SELECT id, url FROM media WHERE url_key IS NULL").fetchall():
        con.execute("UPDATE media SET url_key=? WHERE id=?",
                    (media_key(r["url"]), r["id"]))
    con.execute("CREATE INDEX IF NOT EXISTS idx_media_key "
                "ON media(ad_archive_id, url_key)")
    con.commit()


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def upsert_ad(con, ad):
    """ad: collect.parse_ad() 결과 dict. 신규면 True 반환."""
    ts = now()
    cur = con.execute("SELECT ad_archive_id FROM ads WHERE ad_archive_id=?",
                      (ad["ad_archive_id"],))
    exists = cur.fetchone() is not None
    if exists:
        con.execute(
            """UPDATE ads SET is_active=?, end_date=?, last_seen=?, raw=?,
                              brand=COALESCE(NULLIF(?,''), brand),
                              keyword=COALESCE(NULLIF(?,''), keyword)
               WHERE ad_archive_id=?""",
            (ad.get("is_active"), ad.get("end_date"), ts,
             json.dumps(ad.get("raw"), ensure_ascii=False),
             ad.get("brand") or "", ad.get("keyword") or "",
             ad["ad_archive_id"]),
        )
    else:
        con.execute(
            """INSERT INTO ads (ad_archive_id, page_id, page_name, brand, keyword,
                                is_active, start_date, end_date, platforms, body,
                                title, caption, cta_text, link_url, media_type,
                                first_seen, last_seen, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ad["ad_archive_id"], ad.get("page_id"), ad.get("page_name"),
             ad.get("brand"), ad.get("keyword"), ad.get("is_active"),
             ad.get("start_date"), ad.get("end_date"),
             ",".join(ad.get("platforms") or []), ad.get("body"),
             ad.get("title"), ad.get("caption"), ad.get("cta_text"),
             ad.get("link_url"), ad.get("media_type"), ts, ts,
             json.dumps(ad.get("raw"), ensure_ascii=False)),
        )
    for m in ad.get("media", []):
        key = media_key(m["url"])
        dup = con.execute(
            "SELECT 1 FROM media WHERE ad_archive_id=? AND url_key=?",
            (ad["ad_archive_id"], key)).fetchone()
        if dup:
            continue  # 서명만 바뀐 같은 소재 - 다시 받지 않는다
        con.execute(
            "INSERT OR IGNORE INTO media (ad_archive_id, kind, url, url_key) "
            "VALUES (?,?,?,?)",
            (ad["ad_archive_id"], m["kind"], m["url"], key),
        )
    return not exists


def start_run(con, brand, keyword):
    cur = con.execute(
        "INSERT INTO runs (started_at, brand, keyword) VALUES (?,?,?)",
        (now(), brand, keyword))
    con.commit()
    return cur.lastrowid


def finish_run(con, run_id, found, new_count, note=""):
    con.execute(
        "UPDATE runs SET ended_at=?, found=?, new_count=?, note=? WHERE id=?",
        (now(), found, new_count, note, run_id))
    con.commit()
