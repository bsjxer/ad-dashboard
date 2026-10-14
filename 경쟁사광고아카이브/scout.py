# -*- coding: utf-8 -*-
"""경쟁사 광고 정찰 작업자 (매일 1회)

용량 때문에 두 층으로 나눈다.

  정찰(scout)   카테고리 키워드로 메타 광고 라이브러리를 훑어 새로 시작된 광고를 모은다.
                텍스트·링크만 저장하고 소재 파일은 받지 않는다. 화면의 "결과 ~N개"도
                기록해 카테고리 시장 크기 추이를 본다.
  아카이브      브랜드 레지스트리(brands)에 올린 경쟁사 광고만 소재 파일까지 받는다.
                정찰이 경쟁사 계정·도메인으로 찾은 광고를 그대로 ads 테이블에 넣고,
                run_archive가 영상·이미지를 내려받는다(지금 게재 중인 광고 기준).

경쟁사는 검색에 안 걸리려고 페이지 이름을 위장한다(아랍어·그리스 문자, '키성장 꿀팁모음'
같은 정보성 이름). 그래서 브랜드는 **랜딩 도메인**으로 식별한다.
  - 단축주소(bit.ly 등)는 실제 주소까지 따라가 도메인을 얻는다(links 테이블에 캐시).
  - 등록된 도메인으로 나가는 광고의 페이지가 처음 보는 것이면 → 그 브랜드의 새 계정으로
    자동 등록(source=auto). 다음 실행부터 아카이브 대상이 된다.
  - 직접 등록한 페이지가 처음 보는 도메인으로 나가면 → 그 도메인을 브랜드에 추가.
  - 브랜드별 terms(브랜드명·도메인)로 '정확히 일치' 검색을 따로 돌려 숨은 계정을 찾는다.
판단은 전부 규칙이라 AI 호출이 없다.

결과는 reports/YYYY-MM-DD.json. 웹 대시보드(/report)와 Claude 대화("오늘 리포트")가
같은 파일을 읽는다.

사용법:
  python scout.py daily                      # 동기화 + 정찰 + 아카이브 + 리포트 (cron)
  python scout.py scout | archive | report [--date D] | print [--date D]
  python scout.py brand list
  python scout.py brand add 브랜드 [--category C] [--page ID] [--domain D] [--term T]
  python scout.py brand off|on 브랜드       # 아카이브 끄기/켜기(정찰 식별은 유지)

로그인 없이 돈다. 제약(2026-10-14 서버에서 실측):
  - 페이지 로드 1번에 노출 많은 순 상위 30건까지만 온다(스크롤은 rate limit).
  - URL의 start_date 필터는 '그 기간에 노출된 광고'라서 신규 판별에 못 쓰고,
    정렬 방향(asc)은 무시된다.
그래서 키워드당 전체·영상·이미지로 나눠 최대 90건을 보고, 처음 본 광고를 신규로 센다.
넓은 키워드(수백 건)는 표본이고, 좁은 키워드(성분명 등, 수십 건)는 거의 전수다.
경쟁사는 계정 단위로 따로 훑으므로 새 광고를 놓치지 않는다.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, urlparse

import collect
import db

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "scout_config.json"


def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def today():
    return datetime.now().strftime("%Y-%m-%d")


def day(offset, base=None):
    b = datetime.strptime(base[:10], "%Y-%m-%d") if base else datetime.now()
    return (b + timedelta(days=offset)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- 랜딩 → 브랜드 키
# 이 플랫폼들은 도메인만으로는 누구인지 모른다 → 첫 경로(스토어명·계정명)까지 붙인다
_PATH_PLATFORMS = {"smartstore.naver.com", "brand.naver.com", "m.site.naver.com",
                   "instagram.com", "litt.ly"}


def _host(url):
    try:
        h = urlparse(url or "").netloc.lower().split(":")[0]
    except Exception:
        return ""
    for pre in ("www.", "m."):
        if h.startswith(pre) and h.count(".") >= 2:
            h = h[len(pre):]
    return h


def _norm_landing(v):
    """사람이 넣은 도메인 → Landing.key()와 같은 모양.
    'https://www.alpha-i.kr/x' → 'alpha-i.kr', 'smartstore.naver.com/abc/' → 그대로(스토어명 유지)."""
    v = (v or "").strip().lower()
    v = re.sub(r"^[a-z]+://", "", v).rstrip("/")
    host, _, path = v.partition("/")
    host = _host("https://" + host) or host
    if host in _PATH_PLATFORMS and path:
        return "%s/%s" % (host, path.split("/")[0])
    return host


class Landing:
    """광고 링크 → 브랜드 식별 키. 단축주소는 풀어서 본다."""

    def __init__(self, con, cfg):
        self.con = con
        self.short = set(cfg.get("shorteners", []))
        self.platforms = {_host("https://" + d) for d in cfg.get("store_platforms", [])}
        self._http = None

    def _resolve(self, url):
        row = self.con.execute("SELECT final_url FROM links WHERE url=?", (url,)).fetchone()
        if row:
            return row["final_url"]
        final = None
        try:
            import httpx
            if self._http is None:
                self._http = httpx.Client(
                    timeout=10, follow_redirects=True,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140 Safari/537.36"})
            with self._http.stream("GET", url) as r:
                final = str(r.url)
        except Exception:
            final = None
        self.con.execute("INSERT OR REPLACE INTO links VALUES (?,?,?)",
                         (url, final, db.now()))
        return final

    def key(self, url):
        if not url:
            return None
        h = _host(url)
        if h in self.short:
            final = self._resolve(url)
            if not final:
                return None
            url, h = final, _host(final)
        if h in _PATH_PLATFORMS:
            seg = [s for s in urlparse(url).path.split("/") if s]
            return "%s/%s" % (h, seg[0].lower()) if seg else None
        if not h or h in self.platforms or h in self.short:
            return None   # 쿠팡·페이스북 등: 랜딩만으론 브랜드를 모른다
        return h

    def close(self):
        if self._http:
            self._http.close()


# ---------------------------------------------------------------- 브랜드 레지스트리
def _add_key(con, kind, value, brand, source, label=None):
    """새로 추가됐으면 True."""
    if not value:
        return False
    cur = con.execute(
        "INSERT OR IGNORE INTO brand_keys (kind, value, brand, source, label, added_at) "
        "VALUES (?,?,?,?,?,?)", (kind, str(value), brand, source, label, db.now()))
    return cur.rowcount > 0


def add_brand(con, name, category=None, pages=(), domains=(), terms=(),
              google=None, note=None, source="chat"):
    con.execute(
        "INSERT OR IGNORE INTO brands (name, category, google_advertiser, note, added_at) "
        "VALUES (?,?,?,?,?)", (name, category, google, note, db.now()))
    if category:
        con.execute("UPDATE brands SET category=COALESCE(category, ?) WHERE name=?",
                    (category, name))
    for p in pages:
        _add_key(con, "page", p, name, source)
    for d in domains:
        _add_key(con, "domain", _norm_landing(d), name, source)
    for t in terms:
        _add_key(con, "term", t, name, source)
    con.commit()


def sync_config(con, cfg):
    for b in cfg.get("brands", []):
        add_brand(con, b["name"], b.get("category"), b.get("pages", []),
                  b.get("domains", []), b.get("terms", []),
                  b.get("google_advertiser"), b.get("note"), source="config")


class Registry:
    def __init__(self, con, cfg):
        self.con = con
        self.reload()
        own = cfg.get("own", {})
        self.own_domains = set(own.get("domains", []))
        self.own_names = own.get("page_names", [])
        self.events = []   # 이번 실행에서 자동 발견한 것
        # 공용 스토어(LG 생활건강몰 등)를 쓰는 브랜드는 도메인을 배우면 다른 제품까지 묶인다
        self.no_learn = {b["name"] for b in cfg.get("brands", [])
                         if b.get("learn_domains") is False}

    def reload(self):
        self.archive_brands = {r["name"] for r in self.con.execute(
            "SELECT name FROM brands WHERE archive=1")}
        rows = self.con.execute("SELECT * FROM brand_keys").fetchall()
        self.domain = {r["value"]: r["brand"] for r in rows if r["kind"] == "domain"}
        self.page = {r["value"]: r["brand"] for r in rows if r["kind"] == "page"}
        self.page_src = {r["value"]: r["source"] for r in rows if r["kind"] == "page"}

    def is_own(self, page_name, landing):
        return (landing in self.own_domains
                or any(n and n in (page_name or "") for n in self.own_names))

    def attribute(self, page_id, page_name, landing):
        """광고 하나의 브랜드를 정하고, 그 과정에서 새 계정·도메인을 학습한다."""
        if self.is_own(page_name, landing):
            return "(우리)"
        b_dom = self.domain.get(landing) if landing else None
        b_page = self.page.get(page_id) if page_id else None
        if b_dom and page_id and not b_page:
            # 등록된 랜딩으로 나가는 처음 보는 계정 = 위장 계정
            if _add_key(self.con, "page", page_id, b_dom, "auto", page_name):
                self.page[page_id] = b_dom
                self.page_src[page_id] = "auto"
                self.events.append(("새 계정", b_dom, "%s (%s)" % (page_name, page_id)))
        if (b_page and landing and not b_dom and landing not in self.own_domains
                and b_page not in self.no_learn
                and self.page_src.get(page_id) != "auto"):
            # 직접 등록한 계정이 처음 보는 도메인으로 나감 → 그 브랜드의 도메인
            # (자동 발견 계정에서는 배우지 않는다 — 잘못 묶이면 연쇄로 번진다)
            if _add_key(self.con, "domain", landing, b_page, "auto", page_name):
                self.domain[landing] = b_page
                self.events.append(("새 도메인", b_page, landing))
        return b_dom or b_page


# ---------------------------------------------------------------- 정찰
_COUNT_RE = re.compile(r"결과\s*~?\s*([\d,.]+)\s*(만|천)?\s*개")
_COUNT_EN_RE = re.compile(r"~?\s*([\d,.]+)\s*([KkMm])?\s+results?")


def parse_count(text):
    """라이브러리 화면의 '결과 ~5,100개' / '결과 1.2만개' / '~5,100 results' → 정수."""
    m = _COUNT_RE.search(text or "") or _COUNT_EN_RE.search(text or "")
    if not m:
        return None
    mult = {"만": 10000, "천": 1000, "k": 1000, "m": 1000000}
    num = float(m.group(1).replace(",", ""))
    return int(round(num * mult.get((m.group(2) or "").lower(), 1)))


def exact_url(term, country="KR", active_status="active", media_type="all"):
    return ("https://www.facebook.com/ads/library/?active_status=%s&ad_type=all"
            "&country=%s&media_type=%s&q=%s&search_type=keyword_exact_phrase"
            % (active_status, country, media_type, quote('"%s"' % term)))


def _open(page, url, sink, label, keyword):
    """한 번 열어서 광고를 sink에 담고, 화면의 결과 수를 돌려준다."""
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    ids, _ = collect._harvest(page, label, keyword, sink)
    try:
        page.mouse.wheel(0, 9000)
        page.wait_for_timeout(2500)
        more, _ = collect._harvest(page, label, keyword, sink)
        ids |= more
    except Exception:
        pass
    try:
        n = parse_count(page.inner_text("body"))
    except Exception:
        n = None
    if n is None and not ids:
        n = 0   # '결과 없음' 화면
    return ids, n


def _thumb(ad):
    for kind in ("image", "thumb"):
        for m in ad.get("media") or []:
            if m["kind"] == kind:
                return m["url"]
    return None


def _save_scout_ad(con, ad, category, keyword, landing, brand):
    ts = db.now()
    row = con.execute("SELECT keywords FROM scout_ads WHERE ad_archive_id=?",
                      (ad["ad_archive_id"],)).fetchone()
    if row:
        kws = set(filter(None, (row["keywords"] or "").split(",")))
        kws.add(keyword)
        con.execute(
            "UPDATE scout_ads SET is_active=?, last_seen=?, keywords=?, brand=?, "
            "thumb_url=COALESCE(?, thumb_url) WHERE ad_archive_id=?",
            (ad.get("is_active"), ts, ",".join(sorted(kws)), brand, _thumb(ad),
             ad["ad_archive_id"]))
        return False
    con.execute(
        "INSERT INTO scout_ads (ad_archive_id, category, keywords, page_id, page_name,"
        " is_active, start_date, body, title, cta_text, link_url, media_type,"
        " thumb_url, landing, brand, first_seen, last_seen)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ad["ad_archive_id"], category, keyword, ad.get("page_id"),
         ad.get("page_name"), ad.get("is_active"), ad.get("start_date"),
         ad.get("body"), ad.get("title"), ad.get("cta_text"), ad.get("link_url"),
         ad.get("media_type"), _thumb(ad), landing, brand, ts, ts))
    return True


def _store(con, sink, category, keyword, land, reg):
    new = 0
    for ad in sink.values():
        landing = land.key(ad.get("link_url"))
        brand = reg.attribute(ad.get("page_id"), ad.get("page_name"), landing)
        new += _save_scout_ad(con, ad, category, keyword, landing, brand)
        if brand in reg.archive_brands:
            # 경쟁사 광고는 아카이브(ads)에도 넣는다 — 소재는 run_archive가 받는다
            db.upsert_ad(con, dict(ad, brand=brand, keyword=keyword))
        if ad.get("page_id") in reg.page and ad.get("page_name"):
            # 등록 계정의 현재 표시 이름(위장명)을 남겨 둔다 — 이름을 자주 바꾼다
            con.execute("UPDATE brand_keys SET label=? WHERE kind='page' AND value=?",
                        (ad["page_name"], ad["page_id"]))
    con.commit()
    return new


def _save_count(con, kind, ref_date, category, keyword, n):
    if n is None:
        return
    con.execute("INSERT OR REPLACE INTO scout_counts VALUES (?,?,?,?,?,?)",
                (kind, ref_date, category, keyword, n, db.now()))


def _search(page, url_of, label, keyword):
    """전체로 열고, 결과가 30건을 넘으면 영상·이미지로 나눠 한 번씩 더 연다."""
    sink = {}
    ids, n = _open(page, url_of("all"), sink, label, keyword)
    if (n or 0) > len(ids):
        for mt in ("video", "image"):
            time.sleep(PAUSE)
            _open(page, url_of(mt), sink, label, keyword)
    return sink, n


PAUSE = 3.0


def run_scout(brands_only=False):
    """카테고리 키워드 → 게재 중 광고 수 + 상위 광고. 브랜드 terms·계정 → 경쟁사 광고.
    brands_only: 경쟁사를 막 추가했을 때 카테고리 훑기 없이 경쟁사만 바로 받는다."""
    cfg = load_config()
    country = cfg.get("country", "KR")
    con = db.connect()
    sync_config(con, cfg)
    land, reg = Landing(con, cfg), Registry(con, cfg)
    pw, ctx = collect.launch(headless=True)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    t0, total_new = time.time(), 0

    def step(label, url_of, category, keyword):
        nonlocal total_new
        try:
            sink, n = _search(page, url_of, category, keyword)
        except Exception as e:
            print("  [%s] 실패 %s: %s" % (label, type(e).__name__, e), flush=True)
            return None
        new = _store(con, sink, category, keyword, land, reg)
        total_new += new
        print("  [%s] 게재중 %s · 수집 %d (처음 %d)" % (label, n, len(sink), new), flush=True)
        time.sleep(PAUSE)
        return n

    try:
        for cat in ([] if brands_only else cfg["categories"]):
            cname = cat["name"]
            for kw in cat["keywords"]:
                n = step("%s/%s" % (cname, kw),
                         lambda mt, kw=kw: collect.library_url(kw, None, country, "active", mt),
                         cname, kw)
                _save_count(con, "active", today(), cname, kw, n)
                con.commit()

        # 경쟁사: 정확히 일치 검색(숨은 계정 찾기) + 등록 계정 전체
        for r in con.execute(
                "SELECT k.kind, k.value, k.brand, b.category FROM brand_keys k "
                "JOIN brands b ON b.name=k.brand WHERE k.kind IN ('term','page') "
                "ORDER BY k.kind DESC, k.brand").fetchall():
            if r["kind"] == "term":
                step("%s \"%s\"" % (r["brand"], r["value"]),
                     lambda mt, t=r["value"]: exact_url(t, country, media_type=mt),
                     r["category"], "term:" + r["value"])
            else:
                step("%s 계정 %s" % (r["brand"], r["value"]),
                     lambda mt, pid=r["value"]: collect.library_url(
                         None, pid, country, "active", mt),
                     r["category"], "page:" + r["value"])
    finally:
        try:
            ctx.close()
            pw.stop()
        except Exception:
            pass
        land.close()
        con.close()
    for e in reg.events:
        print("  ★ %s: %s → %s" % e)
    print("[정찰 완료] 처음 본 광고 %d건 · %.0f초" % (total_new, time.time() - t0))


# ---------------------------------------------------------------- 아카이브
def run_archive():
    """정찰이 아카이브(ads)에 넣은 경쟁사 광고의 소재 파일을 받는다.

    처음엔 collect.collect()의 '날짜 구간 쪼개기'로 과거분까지 받으려 했으나, 그 날짜
    필터가 '노출 기간'이라 쪼개도 결과가 줄지 않아 계정 하나에 수십 분이 걸렸다
    (2026-10-14). 정찰이 경쟁사 계정을 매일 열어보므로 그 결과를 그대로 쓴다 —
    대신 과거에 이미 끝난 광고는 받지 않는다(로그인 없이 볼 방법이 없다).
    """
    cfg = load_config()
    con = db.connect()
    brands = [r["name"] for r in con.execute("SELECT name FROM brands WHERE archive=1")]
    for b in brands:
        n = collect.download_media(con, b, limit=300)
        print("[아카이브] %s: 소재 %d개 저장" % (b, n), flush=True)
    # 3일 연속 정찰에서 안 보이면 종료된 것으로 본다
    con.execute("UPDATE ads SET is_active=0 WHERE is_active=1 AND last_seen<? AND brand IN "
                "(SELECT name FROM brands WHERE archive=1)", (day(-3) + " 00:00:00",))
    con.execute("UPDATE brand_keys SET last_run=? WHERE kind='page' AND brand IN "
                "(SELECT name FROM brands WHERE archive=1)", (db.now(),))
    con.commit()

    # 아카이브한 광고에서도 도메인을 배운다(직접 등록한 계정 → 새 랜딩 도메인)
    land, reg = Landing(con, cfg), Registry(con, cfg)
    for a in con.execute("SELECT page_id, page_name, link_url FROM ads "
                         "WHERE substr(last_seen,1,10)=?", (today(),)).fetchall():
        reg.attribute(a["page_id"], a["page_name"], land.key(a["link_url"]))
    con.commit()
    land.close()
    con.close()
    for e in reg.events:
        print("  ★ %s: %s → %s" % e)


# ---------------------------------------------------------------- 리포트
STOP = set("""광고 지금 바로 있는 하는 위한 위해 그리고 하지만 정말 진짜 너무 많이 모든 이제
우리 함께 가장 최고 오늘 확인 구매 할인 무료 배송 이벤트 혜택 특가 공식 제품 상품 브랜드
보세요 하세요 드립니다 있습니다 합니다 됩니다 입니다 있어요 해요 에서 으로 에게 the and for
you your with our https http www com co kr""".split())
_TOKEN_RE = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z0-9]+")


_JOSA = ("으로", "에서", "에게", "까지", "부터", "처럼", "보다", "이", "가", "을", "를",
         "은", "는", "의", "에", "도", "로", "와", "과")


def _stem(t):
    # 조사 떼기(가격이→가격, 아이가→아이). 두 글자 이하는 건드리지 않는다(아이·키가 깨지지 않게)
    if len(t) > 2 and "가" <= t[-1] <= "힣":
        for j in _JOSA:
            if t.endswith(j) and len(t) - len(j) >= 2:
                return t[:-len(j)]
    return t


def _tokens(text):
    out = set()
    for t in _TOKEN_RE.findall(text or ""):
        t = _stem(t.lower())
        if len(t) >= 2 and t not in STOP:
            out.add(t)
    return out


def _clean(text, n=None):
    """보이지 않는 공백(⠀ 등)·줄바꿈을 한 칸으로."""
    t = re.sub(r"[\s\u2800\u200b\u3164]+", " ", text or "").strip()
    return t[:n] if n else t


def lib_link(ad_id):
    return "https://www.facebook.com/ads/library/?id=%s" % ad_id


def page_link(page_id):
    return ("https://www.facebook.com/ads/library/?active_status=all&ad_type=all"
            "&country=KR&view_all_page_id=%s&search_type=page" % page_id)


def build_report(date=None):
    date = date or today()
    d1, d7, d28 = day(-1, date), day(-7, date), day(-28, date)
    cfg = load_config()
    con = db.connect()

    brands = {r["name"]: dict(r) for r in con.execute("SELECT * FROM brands")}
    auto_today = [dict(r) for r in con.execute(
        "SELECT * FROM brand_keys WHERE source='auto' AND substr(added_at,1,10)=?", (date,))]

    cats = []
    for cat in cfg["categories"]:
        cname = cat["name"]

        def counts(kind, ref):
            return {r["keyword"]: r["n"] for r in con.execute(
                "SELECT keyword, n FROM scout_counts WHERE kind=? AND ref_date=? "
                "AND category=?", (kind, ref, cname))}

        act_now, act_wk = counts("active", date), counts("active", d7)
        # 신규 시작 수는 화면 수치를 얻을 수 없어서(날짜 필터 = 노출 기간) 포착 기준으로 센다
        def caught(lo, hi):
            out = collections.Counter()
            for r in con.execute(
                    "SELECT keywords FROM scout_ads WHERE category=? AND "
                    "start_date BETWEEN ? AND ?", (cname, lo, hi)):
                out.update((r["keywords"] or "").split(","))
            return out
        st_y, st_wk = caught(d1, d1), caught(d7, day(-2, date))
        kw_rows = [{"keyword": kw, "active": act_now.get(kw),
                    "active_7d_ago": act_wk.get(kw),
                    "started_yesterday": st_y.get(kw, 0),
                    "started_avg_7d": round(st_wk.get(kw, 0) / 6, 1)}
                   for kw in cat["keywords"]]

        # 신규 광고 = 오늘 처음 봤고 3일 안에 시작한 것 (우리 광고 제외)
        new_ads = [dict(r) for r in con.execute(
            "SELECT * FROM scout_ads WHERE category=? AND substr(first_seen,1,10)=? "
            "AND start_date>=? AND IFNULL(brand,'')<>'(우리)' ORDER BY start_date DESC",
            (cname, date, day(-3, date)))]

        # 누가 광고를 많이 냈나 — 브랜드(식별되면) 또는 랜딩 도메인 단위로 묶는다
        groups = collections.defaultdict(list)
        for a in new_ads:
            groups[a["brand"] or a["landing"] or ("page:" + (a["page_id"] or "?"))].append(a)
        top = []
        for g, ads in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:12]:
            top.append({"who": g, "known": g in brands, "new_ads": len(ads),
                        "pages": sorted({a["page_name"] or "?" for a in ads}),
                        "landing": ads[0]["landing"],
                        "library": page_link(ads[0]["page_id"])})

        # 처음 포착한 랜딩(브랜드 후보): 오늘 처음 본 도메인 + 가장 이른 광고가 7일 내 시작
        new_landings = []
        for r in con.execute(
                "SELECT landing, MIN(first_seen) fs, MIN(start_date) sd, COUNT(*) n, "
                "GROUP_CONCAT(DISTINCT page_name) pages, MAX(ad_archive_id) ad "
                "FROM scout_ads WHERE category=? AND landing IS NOT NULL "
                "AND IFNULL(brand,'')='' GROUP BY landing "
                "HAVING substr(fs,1,10)=? AND sd>=?", (cname, date, d7)):
            s = con.execute("SELECT title, body, page_id FROM scout_ads "
                            "WHERE ad_archive_id=?", (r["ad"],)).fetchone()
            new_landings.append({
                "landing": r["landing"], "ads": r["n"], "first_start": r["sd"],
                "pages": (r["pages"] or "").split(","),
                "sample": _clean(s["title"] or s["body"], 120) if s else "",
                "library": page_link(s["page_id"]) if s else None})
        new_landings.sort(key=lambda b: -b["ads"])

        # 등록 경쟁사 현황
        comp = []
        for bname, b in brands.items():
            if b["category"] != cname:
                continue
            n_new = sum(1 for a in new_ads if a["brand"] == bname)
            active = con.execute(
                "SELECT COUNT(*) c FROM (SELECT ad_archive_id FROM scout_ads WHERE "
                "brand=? AND is_active=1 UNION SELECT ad_archive_id FROM ads WHERE "
                "brand=? AND is_active=1)", (bname, bname)).fetchone()["c"]
            pages = con.execute("SELECT COUNT(*) c FROM brand_keys WHERE brand=? "
                                "AND kind='page'", (bname,)).fetchone()["c"]
            arch_new = con.execute("SELECT COUNT(*) c FROM ads WHERE brand=? AND "
                                   "substr(first_seen,1,10)=?", (bname, date)).fetchone()["c"]
            comp.append({"brand": bname, "active_ads": active, "new_ads": n_new,
                         "archived_new": arch_new, "pages": pages,
                         "found_today": [k for k in auto_today if k["brand"] == bname]})

        # 표현: 신규 광고에 많이 나온 단어. 지난 28일 대비 비중이 뛴 것은 '급상승'
        base = [dict(r) for r in con.execute(
            "SELECT body, title, brand, landing, page_id FROM scout_ads WHERE category=? AND "
            "substr(first_seen,1,10) BETWEEN ? AND ?", (cname, d28, d1))]
        # 한 브랜드가 같은 문구로 광고 수십 개를 돌리면 그 단어가 1등이 된다 →
        # '그 표현을 쓴 광고주 수'로 센다(브랜드/랜딩 단위로 한 번씩).
        def by_who(rows):
            g = collections.defaultdict(set)
            for a in rows:
                who = a.get("brand") or a.get("landing") or a.get("page_id") or "?"
                g[who] |= _tokens((a.get("body") or "") + " " + (a.get("title") or ""))
            c = collections.Counter()
            for toks in g.values():
                c.update(toks)
            return c, max(len(g), 1)
        cnt_new, n_new = by_who(new_ads)
        cnt_base, n_base = by_who(base)
        words = []
        for w, c in cnt_new.most_common(40):
            if c < 2:
                continue
            rising = bool(base) and (c / n_new >= 2 * cnt_base[w] / n_base + 0.05)
            words.append({"word": w, "ads": c, "rising": rising})
            if len(words) >= 15:
                break

        samples = [{"id": a["ad_archive_id"],
                    "who": a["brand"] or a["landing"] or a["page_name"],
                    "page_name": a["page_name"], "start_date": a["start_date"],
                    "media_type": a["media_type"],
                    "text": _clean((a["title"] or "") + " " + (a["body"] or ""), 160),
                    "thumb_url": a["thumb_url"], "library": lib_link(a["ad_archive_id"])}
                   for a in new_ads[:12]]

        cats.append({"name": cname, "ours": cat.get("ours"), "keywords": kw_rows,
                     "competitors": comp, "new_ads": len(new_ads), "top": top,
                     "new_landings": new_landings[:15], "words": words,
                     "samples": samples})

    first_day = con.execute(
        "SELECT MIN(substr(first_seen,1,10)) d FROM scout_ads").fetchone()["d"]
    con.close()
    rep = {"date": date, "generated_at": db.now(), "categories": cats,
           "discovered": auto_today,
           # 정찰 첫날엔 모든 랜딩을 '처음 봄'으로 잡는다 — 7일 쌓여야 의미가 있다
           "baseline_days": ((datetime.strptime(date, "%Y-%m-%d")
                              - datetime.strptime(first_day, "%Y-%m-%d")).days
                             if first_day else 0)}
    path = db.REPORT_DIR / ("%s.json" % date)
    path.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print("[리포트] " + str(path))
    return rep


def load_report(date=None):
    if date:
        p = db.REPORT_DIR / ("%s.json" % date)
    else:
        files = sorted(db.REPORT_DIR.glob("????-??-??.json"))
        p = files[-1] if files else None
    if not p or not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _fmt(n):
    return "-" if n is None else "{:,}".format(int(round(n)))


def _delta(now, before):
    if now is None or not before:
        return ""
    return " (%+.0f%%)" % ((now - before) / before * 100)


def format_report(rep):
    """대화·로그용 텍스트."""
    L = ["# 경쟁사 광고 리포트 %s" % rep["date"]]
    if rep.get("baseline_days", 0) < 7:
        L.append("※ 정찰 %d일째 — 추이·신규 브랜드는 7일 쌓여야 믿을 만합니다."
                 % (rep.get("baseline_days", 0) + 1))
    if rep.get("discovered"):
        L.append("\n★ 오늘 자동 발견")
        for k in rep["discovered"]:
            L.append("  - %s: %s %s %s" % (k["brand"], k["kind"], k["value"], k["label"] or ""))
    for c in rep["categories"]:
        L.append("\n## %s%s" % (c["name"], " (우리: %s)" % c["ours"] if c.get("ours") else ""))
        L.append("키워드 | 게재중 | 어제 시작(포착) | 7일 일평균(포착)")
        for k in c["keywords"]:
            L.append("%s | %s%s | %s | %s" % (
                k["keyword"], _fmt(k["active"]), _delta(k["active"], k["active_7d_ago"]),
                _fmt(k["started_yesterday"]), _fmt(k["started_avg_7d"])))
        if c["competitors"]:
            L.append("등록 경쟁사:")
            for b in c["competitors"]:
                L.append("  - %s: 게재중 %d · 신규 %d · 아카이브 신규 %d · 계정 %d"
                         % (b["brand"], b["active_ads"], b["new_ads"],
                            b["archived_new"], b["pages"]))
        L.append("신규 광고 %d건" % c["new_ads"])
        if c["top"]:
            L.append("광고 많이 낸 곳: " + ", ".join(
                "%s %d%s" % (t["who"], t["new_ads"], "★" if t["known"] else "")
                for t in c["top"][:8]))
        if c["new_landings"]:
            L.append("처음 포착한 랜딩(브랜드 후보):")
            for b in c["new_landings"][:8]:
                L.append("  - %s (광고 %d, %s~, 계정: %s) %s"
                         % (b["landing"], b["ads"], b["first_start"],
                            "/".join(b["pages"][:3]), b["sample"][:50]))
        if c["words"]:
            L.append("많이 쓴 표현(광고주 수): " + ", ".join(
                "%s %d%s" % (w["word"], w["ads"], "↑" if w["rising"] else "")
                for w in c["words"][:12]))
    return "\n".join(L)


# ---------------------------------------------------------------- CLI
def brand_rows(con):
    return [dict(r) for r in con.execute(
        "SELECT b.*, (SELECT COUNT(*) FROM brand_keys k WHERE k.brand=b.name AND "
        "k.kind='page') pages, (SELECT GROUP_CONCAT(value, ' ') FROM brand_keys k "
        "WHERE k.brand=b.name AND k.kind='domain') domains, (SELECT COUNT(*) FROM "
        "ads a WHERE a.brand=b.name) archived FROM brands b ORDER BY b.category, b.name")]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="경쟁사 광고 정찰 작업자")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daily")
    sub.add_parser("scout").add_argument("--brands-only", action="store_true",
                                         help="경쟁사 계정·검색어만 (카테고리 훑기 생략)")
    sub.add_parser("archive")
    for name in ("report", "print"):
        sub.add_parser(name).add_argument("--date")
    bp = sub.add_parser("brand")
    bsub = bp.add_subparsers(dest="bcmd", required=True)
    bsub.add_parser("list")
    ba = bsub.add_parser("add")
    ba.add_argument("name")
    ba.add_argument("--category")
    ba.add_argument("--page", action="append", default=[])
    ba.add_argument("--domain", action="append", default=[])
    ba.add_argument("--term", action="append", default=[])
    ba.add_argument("--note")
    for name in ("off", "on"):
        bsub.add_parser(name).add_argument("name")
    a = p.parse_args()

    if a.cmd == "daily":
        print("===== %s 시작" % db.now(), flush=True)
        run_scout()
        run_archive()
        print(format_report(build_report()))
    elif a.cmd == "scout":
        run_scout(brands_only=a.brands_only)
    elif a.cmd == "archive":
        run_archive()
    elif a.cmd == "report":
        print(format_report(build_report(a.date)))
    elif a.cmd == "print":
        rep = load_report(a.date)
        print(format_report(rep) if rep else "리포트 없음")
    elif a.cmd == "brand":
        con = db.connect()
        if a.bcmd == "list":
            for b in brand_rows(con):
                print("%-10s %-8s 아카이브=%s 계정 %d · 도메인 %s · 저장 %d건"
                      % (b["name"], b["category"] or "-", b["archive"], b["pages"],
                         b["domains"] or "-", b["archived"]))
        elif a.bcmd == "add":
            add_brand(con, a.name, a.category, a.page, a.domain, a.term,
                      note=a.note, source="chat")
            print("등록: " + a.name)
        else:
            con.execute("UPDATE brands SET archive=? WHERE name=?",
                        (1 if a.bcmd == "on" else 0, a.name))
            con.commit()
            print("%s: 아카이브 %s" % (a.name, a.bcmd))
        con.close()


if __name__ == "__main__":
    main()
