# -*- coding: utf-8 -*-
"""경쟁사 광고 아카이빙 수집기 (Meta 광고 라이브러리)

Meta 공식 Ad Library API는 정치·사회이슈 광고만 제공하므로,
공개 광고 라이브러리 페이지가 내부적으로 받아오는 JSON 응답을
브라우저 안에서 가로채(intercept) 구조화된 데이터로 저장한다.

사용법:
  python collect.py --login                        # 최초 1회 로그인(세션 저장)
  python collect.py --brand 브랜드명 --keyword 키워드
  python collect.py --brand 브랜드명 --page-id 1234567890
  python collect.py --targets targets.json         # 일괄 수집
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import db

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / "browser_profile"

INIT_SCRIPT = r"""
(() => {
  if (window.__adcapInstalled) return;
  window.__adcapInstalled = true;
  window.__adcap = [];
  const want = (u) => /search_ads|api\/graphql/.test(u || '');
  const push = (t) => { if (t && t.length > 40) window.__adcap.push(t); };

  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const res = await origFetch.apply(this, args);
    try {
      const a0 = args[0];
      const url = (typeof a0 === 'string') ? a0 : (a0 && a0.url) || '';
      if (want(url)) res.clone().text().then(push).catch(() => {});
    } catch (e) {}
    return res;
  };

  const oOpen = XMLHttpRequest.prototype.open;
  const oSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u, ...rest) {
    this.__adcapUrl = u;
    return oOpen.call(this, m, u, ...rest);
  };
  XMLHttpRequest.prototype.send = function (...rest) {
    this.addEventListener('load', () => {
      try { if (want(this.__adcapUrl)) push(this.responseText); } catch (e) {}
    });
    return oSend.apply(this, rest);
  };
})();
"""

# 첫 페이지 결과는 XHR 이 아니라 HTML 문서 안 <script type="application/json">
# 페이로드로 심겨서 온다. 그래서 DOM 에서도 같이 긁어야 한다.
DOM_JSON_JS = """() =>
  Array.from(document.querySelectorAll('script[type="application/json"]'))
    .map(s => s.textContent)
    .filter(t => t && (t.indexOf('ad_archive_id') >= 0
                       || t.indexOf('adArchiveID') >= 0))"""


# ---------------------------------------------------------------- JSON 파싱
def _loads_all(text):
    """for(;;); 접두사 / 줄단위 다중 JSON 을 모두 파싱해서 객체 리스트로."""
    out = []
    text = (text or "").strip()
    for prefix in ("for (;;);", "for(;;);"):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    for chunk in text.split("\n"):
        chunk = chunk.strip()
        if not chunk or chunk[0] not in "{[":
            continue
        try:
            out.append(json.loads(chunk))
        except Exception:
            pass
    if not out:
        try:
            out.append(json.loads(text))
        except Exception:
            pass
    return out


AD_ID_KEYS = ("adArchiveID", "ad_archive_id", "adArchiveId")


def find_ads(node, acc=None):
    """중첩 JSON 어디에 있든 광고 객체(adArchiveID 보유)를 재귀로 찾아낸다."""
    if acc is None:
        acc = []
    if isinstance(node, dict):
        if any(k in node for k in AD_ID_KEYS):
            acc.append(node)
        for v in node.values():
            find_ads(v, acc)
    elif isinstance(node, list):
        for v in node:
            find_ads(v, acc)
    return acc


def g(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return default


def _epoch_to_date(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v > 10000000000:  # milliseconds
        v //= 1000
    return datetime.fromtimestamp(v, tz=timezone.utc).strftime("%Y-%m-%d")


def _text_of(v):
    """body 는 문자열 / {'text':..} / {'markup':{'__html':..}} 형태가 섞여 있다."""
    if v is None:
        return None
    if isinstance(v, str):
        return re.sub(r"<[^>]+>", "", v).strip() or None
    if isinstance(v, dict):
        for k in ("text", "markup", "__html"):
            if k in v:
                return _text_of(v[k])
    return None


def _collect_media(snap):
    media = []
    seen = set()

    def add(kind, url):
        if url and isinstance(url, str) and url not in seen:
            seen.add(url)
            media.append({"kind": kind, "url": url})

    def walk(node):
        if isinstance(node, dict):
            for key in ("original_image_url", "originalImageURL",
                        "resized_image_url", "resizedImageUrl"):
                if node.get(key):
                    add("image", node[key])
                    break
            for key in ("video_hd_url", "videoHdUrl",
                        "video_sd_url", "videoSdUrl"):
                if node.get(key):
                    add("video", node[key])
                    break
            for key in ("video_preview_image_url", "videoPreviewImageUrl"):
                if node.get(key):
                    add("thumb", node[key])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(snap)
    return media


def parse_ad(obj, brand="", keyword=""):
    ad_id = str(g(obj, *AD_ID_KEYS, default="") or "")
    if not ad_id:
        return None
    snap = g(obj, "snapshot", default={}) or {}
    cards = g(snap, "cards", default=[]) or []
    first_card = cards[0] if isinstance(cards, list) and cards else {}

    platforms = (g(obj, "publisherPlatform", "publisher_platform")
                 or g(snap, "publisher_platform", "publisherPlatform", default=[]))
    if isinstance(platforms, str):
        platforms = [platforms]
    platforms = [str(p) for p in (platforms or [])]

    body = (_text_of(g(snap, "body")) or _text_of(g(first_card, "body"))
            or _text_of(g(snap, "link_description", "linkDescription")))
    title = _text_of(g(snap, "title")) or _text_of(g(first_card, "title"))
    caption = _text_of(g(snap, "caption")) or _text_of(g(first_card, "caption"))
    cta = (_text_of(g(snap, "cta_text", "ctaText"))
           or _text_of(g(first_card, "cta_text", "ctaText")))
    link = g(snap, "link_url", "linkUrl") or g(first_card, "link_url", "linkUrl")

    media = _collect_media(snap)
    kinds = set(m["kind"] for m in media)
    if "video" in kinds:
        media_type = "video"
    elif "image" in kinds:
        media_type = "image"
    else:
        media_type = "text"

    is_active = g(obj, "isActive", "is_active")
    if isinstance(is_active, bool):
        is_active = int(is_active)

    return {
        "ad_archive_id": ad_id,
        "page_id": str(g(obj, "pageID", "page_id", default="") or ""),
        "page_name": (g(obj, "pageName", "page_name")
                      or g(snap, "page_name", "pageName")),
        "brand": brand,
        "keyword": keyword,
        "is_active": is_active,
        "start_date": _epoch_to_date(g(obj, "startDate", "start_date")),
        "end_date": _epoch_to_date(g(obj, "endDate", "end_date")),
        "platforms": platforms,
        "body": body,
        "title": title,
        "caption": caption,
        "cta_text": cta,
        "link_url": link,
        "media_type": media_type,
        "media": media,
        "raw": obj,
    }


# ---------------------------------------------------------------- 브라우저
def library_url(keyword=None, page_id=None, country="KR",
                active_status="all", media_type="all",
                date_min=None, date_max=None):
    base = ("https://www.facebook.com/ads/library/?active_status=" + active_status
            + "&ad_type=all&country=" + country + "&media_type=" + media_type)
    if date_min:
        base += "&start_date[min]=" + date_min
    if date_max:
        base += "&start_date[max]=" + date_max
    if page_id:
        return base + "&view_all_page_id=" + str(page_id) + "&search_type=page"
    return base + "&q=" + quote(keyword or "") + "&search_type=keyword_unordered"


def launch(headless=False):
    from playwright.sync_api import sync_playwright
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        headless=headless,
        viewport={"width": 1440, "height": 1000},
        locale="ko-KR",
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx.add_init_script(INIT_SCRIPT)
    return pw, ctx


def logged_in(ctx):
    try:
        return any(c["name"] == "c_user" for c in ctx.cookies())
    except Exception:
        return False


def do_login(timeout=420):
    """크롬 창을 띄우고, 로그인이 감지되면 자동으로 세션을 저장하고 닫는다."""
    pw, ctx = launch(headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    if logged_in(ctx):
        print("이미 로그인된 세션이 있습니다 -> " + str(PROFILE_DIR))
        ctx.close()
        pw.stop()
        return True

    page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
    print("크롬 창에서 페이스북에 로그인하세요.")
    print("로그인이 감지되면 자동으로 저장하고 창을 닫습니다. (최대 %d초 대기)" % timeout)

    deadline = time.time() + timeout
    ok = False
    while time.time() < deadline:
        if logged_in(ctx):
            ok = True
            break
        try:
            page.title()  # 창을 닫았는지 확인
        except Exception:
            print("브라우저 창이 닫혔습니다.")
            break
        time.sleep(3)

    if ok:
        print("로그인 감지됨. 광고 라이브러리 접근 확인 중...")
        try:
            page.goto(library_url(keyword="광고"), wait_until="domcontentloaded",
                      timeout=60000)
            page.wait_for_timeout(6000)
            n = len(dom_payloads(page))
            print("  광고 라이브러리 정상 (페이로드 %d개)" % n)
        except Exception as e:
            print("  확인 실패: " + type(e).__name__)
        print("세션 저장 완료 -> " + str(PROFILE_DIR))
    else:
        print("로그인이 감지되지 않았습니다. 다시 실행해 주세요.")

    try:
        ctx.close()
        pw.stop()
    except Exception:
        pass
    return ok


def drain(page):
    """가로챈 XHR 응답 본문을 꺼내오고 버퍼를 비운다."""
    try:
        return page.evaluate(
            "() => { const a = window.__adcap || []; window.__adcap = []; return a; }")
    except Exception:
        return []


def dom_payloads(page):
    """HTML 문서에 심긴 JSON 페이로드(첫 페이지 결과)를 꺼내온다."""
    try:
        return page.evaluate(DOM_JSON_JS)
    except Exception:
        return []


# 로그인 없이 페이지 로드 한 번으로 받을 수 있는 최대 건수.
# 이 수에 걸린 구간은 결과가 잘렸다는 뜻이므로 기간을 더 쪼갠다.
PAGE_CAP = 30


def _harvest(page, brand, keyword, sink):
    """현재 페이지에서 광고를 긁어 sink 에 넣는다. (이번 구간 id 집합, rate limit 여부)"""
    ids = set()
    rate = False
    for txt in drain(page) + dom_payloads(page):
        if "Rate limit exceeded" in txt:
            rate = True
        for doc in _loads_all(txt):
            for obj in find_ads(doc):
                ad = parse_ad(obj, brand, keyword or "")
                if ad:
                    ids.add(ad["ad_archive_id"])
                    if ad["ad_archive_id"] not in sink:
                        sink[ad["ad_archive_id"]] = ad
    return ids, rate


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d")


def _s(d):
    return d.strftime("%Y-%m-%d")


def _load_slice(page, sink, brand, keyword, page_id, country, active_status,
                media_type, lo, hi, scroll_pause, scroll_rounds=60):
    """한 구간을 열고 끝까지 스크롤한다.

    반환: (id 집합, 결과가 잘렸는지 여부)
    스크롤이 rate limit 으로 막히거나 스크롤 횟수를 다 쓰고도 계속 늘고 있었다면
    이 구간은 잘린 것이므로, 호출한 쪽에서 기간을 더 쪼개야 한다.
    """
    url = library_url(keyword, page_id, country, active_status, media_type, lo, hi)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    ids, rate = _harvest(page, brand, keyword, sink)

    idle = 0
    finished = False
    for _ in range(scroll_rounds):
        before = len(ids)
        try:
            page.keyboard.press("End")
            page.mouse.wheel(0, 9000)
        except Exception:
            break
        page.wait_for_timeout(int(scroll_pause * 1000))
        more, r = _harvest(page, brand, keyword, sink)
        ids |= more
        rate = rate or r
        if len(ids) == before:
            idle += 1
            if idle >= 2:
                finished = True   # 더 이상 안 늘어남 = 이 구간은 다 받았다
                break
        else:
            idle = 0

    truncated = (rate and len(ids) >= PAGE_CAP) or not finished
    return ids, truncated


def collect(brand, keyword=None, page_id=None, country="KR", max_ads=200,
            headless=False, download=True, active_status="all",
            media_type="all", scroll_pause=2.5, since=None, until=None):
    """게재 시작일 구간을 쪼개가며 수집한다.

    로그인 없이는 페이스북이 스크롤(페이지네이션) 요청을 rate limit 으로 막기
    때문에, 한 번의 페이지 로드로 오는 30건만 받을 수 있다. 그래서 기간을
    잘게 나눠 여러 번 로드하고, 30건에 걸린 구간은 절반으로 다시 쪼갠다.
    """
    con = db.connect()
    run_id = db.start_run(con, brand, keyword or ("page:" + str(page_id)))

    until = until or _s(datetime.now())
    since = since or _s(datetime.now() - timedelta(days=730))

    pw, ctx = launch(headless=headless)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    sink = {}
    new_count = 0
    rate_hit = False
    loads = 0
    capped_days = []

    def run_slice(lo, hi, mt=media_type):
        nonlocal loads, rate_hit
        ids, truncated = _load_slice(page, sink, brand, keyword, page_id, country,
                                     active_status, mt, lo, hi, scroll_pause)
        loads += 1
        rate_hit = rate_hit or truncated
        span = "%s~%s" % (lo, hi) if lo != hi else lo
        extra = "" if mt == media_type else " (%s)" % mt
        print("  [%s]%s %d건%s · 누적 %d"
              % (span, extra, len(ids), " (잘림)" if truncated else "", len(sink)))
        return ids, truncated

    try:
        queue = [(since, until)]
        while queue and len(sink) < max_ads:
            lo, hi = queue.pop(0)
            ids, truncated = run_slice(lo, hi)

            # 끝까지 스크롤해서 다 받았으면 쪼갤 이유가 없다
            if not truncated:
                continue
            # 결과가 잘렸다 -> 기간을 절반으로 쪼갠다
            days = (_d(hi) - _d(lo)).days
            if days >= 1:
                mid = _d(lo) + timedelta(days=days // 2)
                queue.append((lo, _s(mid)))
                queue.append((_s(mid + timedelta(days=1)), hi))
            elif media_type == "all":
                # 하루 안에서도 잘리면 소재 유형으로 한 번 더 쪼갠다
                for mt in ("image", "video"):
                    if len(sink) >= max_ads:
                        break
                    run_slice(lo, hi, mt)
            else:
                capped_days.append(lo)

        if not sink:
            print("  [경고] 수집 0건. 로그인이 필요할 수 있습니다"
                  " (python collect.py --login), 또는 검색 결과가 없습니다.")
        elif rate_hit:
            print("  (일부 구간이 잘려 기간 분할로 우회 수집했습니다."
                  " python collect.py --login 하면 더 빠르고 깊게 긁힙니다.)")
        if capped_days:
            print("  [주의] 하루 단위로도 30건에 걸린 날: %s"
                  % ", ".join(capped_days[:5]))
    finally:
        try:
            ctx.close()
            pw.stop()
        except Exception:
            pass

    ads = list(sink.values())[:max_ads]
    for ad in ads:
        if db.upsert_ad(con, ad):
            new_count += 1
    con.commit()

    if download:
        print("  미디어 %d개 저장" % download_media(con, brand))

    db.finish_run(con, run_id, len(ads), new_count,
                  note="loads=%d" % loads)
    print("[완료] %s: 총 %d건 (신규 %d건, 페이지 로드 %d회)"
          % (brand, len(ads), new_count, loads))
    con.close()
    return len(ads), new_count


# ---------------------------------------------------------------- 미디어 저장
def _safe(s):
    return re.sub(r'[\\/:*?"<>|]+', "_", (s or "unknown")).strip() or "unknown"


def download_media(con, brand=None, limit=500):
    import httpx
    q = ("SELECT m.id, m.ad_archive_id, m.kind, m.url, a.brand FROM media m "
         "JOIN ads a ON a.ad_archive_id = m.ad_archive_id "
         "WHERE (m.local_path IS NULL OR m.local_path = '')")
    args = []
    if brand:
        q += " AND a.brand = ?"
        args.append(brand)
    q += " LIMIT ?"
    args.append(limit)
    rows = con.execute(q, args).fetchall()
    if not rows:
        return 0

    saved = 0
    headers = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/126.0 Safari/537.36")}
    with httpx.Client(timeout=60, follow_redirects=True, headers=headers) as cli:
        for r in rows:
            ext = ".mp4" if r["kind"] == "video" else ".jpg"
            m = re.search(r"\.(jpe?g|png|webp|gif|mp4)", r["url"] or "", re.I)
            if m:
                ext = "." + m.group(1).lower()
            folder = db.MEDIA_DIR / _safe(r["brand"])
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / ("%s_%s_%s%s" % (r["ad_archive_id"], r["kind"], r["id"], ext))
            try:
                resp = cli.get(r["url"])
                resp.raise_for_status()
                dest.write_bytes(resp.content)
                rel = str(dest.relative_to(db.MEDIA_DIR)).replace("\\", "/")
                con.execute("UPDATE media SET local_path=? WHERE id=?", (rel, r["id"]))
                saved += 1
            except Exception as e:
                con.execute("UPDATE media SET local_path=? WHERE id=?",
                            ("FAILED", r["id"]))
                print("    미디어 실패: " + type(e).__name__)
    con.commit()
    return saved


# ---------------------------------------------------------------- CLI
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    p = argparse.ArgumentParser(description="경쟁사 광고 아카이빙 수집기")
    p.add_argument("--login", action="store_true", help="페이스북 로그인 세션 저장")
    p.add_argument("--login-timeout", type=int, default=420,
                   help="로그인 감지 대기 초 (기본 420)")
    p.add_argument("--brand", help="아카이브에 기록할 브랜드 라벨")
    p.add_argument("--keyword", help="광고 라이브러리 검색 키워드")
    p.add_argument("--page-id", help="특정 페이지의 광고 전체 (view_all_page_id)")
    p.add_argument("--targets", help="브랜드 목록 JSON 파일로 일괄 수집")
    p.add_argument("--country", default="KR")
    p.add_argument("--max", type=int, default=200, help="브랜드당 최대 수집 건수")
    p.add_argument("--active-status", default="all",
                   choices=["all", "active", "inactive"])
    p.add_argument("--media-type", default="all",
                   choices=["all", "image", "video", "meme", "image_and_meme", "none"])
    p.add_argument("--headless", action="store_true")
    p.add_argument("--no-media", action="store_true", help="미디어 파일 다운로드 생략")
    p.add_argument("--pause", type=float, default=2.5,
                   help="스크롤 간 대기 초 (rate limit 걸리면 늘리세요)")
    p.add_argument("--since", help="게재 시작일 하한 (YYYY-MM-DD, 기본 2년 전)")
    p.add_argument("--until", help="게재 시작일 상한 (YYYY-MM-DD, 기본 오늘)")
    a = p.parse_args()

    if a.login:
        do_login(a.login_timeout)
        return

    jobs = []
    if a.targets:
        data = json.loads(Path(a.targets).read_text(encoding="utf-8"))
        items = data.get("targets", data) if isinstance(data, dict) else data
        for t in items:
            jobs.append({
                "brand": t.get("brand") or t.get("name"),
                "keyword": t.get("keyword"),
                "page_id": t.get("page_id"),
                "max_ads": int(t.get("max", a.max)),
            })
    elif a.brand and (a.keyword or a.page_id):
        jobs.append({"brand": a.brand, "keyword": a.keyword,
                     "page_id": a.page_id, "max_ads": a.max})
    else:
        p.error("--brand 와 (--keyword 또는 --page-id), 또는 --targets 가 필요합니다")

    total_new = 0
    for j in jobs:
        try:
            _, n = collect(j["brand"], j.get("keyword"), j.get("page_id"),
                           country=a.country, max_ads=j["max_ads"],
                           headless=a.headless, download=not a.no_media,
                           active_status=a.active_status, media_type=a.media_type,
                           scroll_pause=a.pause, since=a.since, until=a.until)
            total_new += n
        except Exception as e:
            print("[오류] %s: %s: %s" % (j["brand"], type(e).__name__, e))
    print("\n신규 광고 합계: %d건" % total_new)


if __name__ == "__main__":
    main()
