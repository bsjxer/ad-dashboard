# -*- coding: utf-8 -*-
"""경쟁사 광고 아카이브 - 웹 대시보드

  python web.py           ->  http://localhost:8011

화면: 리포트(일일 정찰 결과) · 정찰(카테고리 신규 광고) · 경쟁사(브랜드 레지스트리) ·
      아카이브(소재까지 저장한 광고).
서버에서는 gunicorn으로 띄우고 nginx가 앞에 선다. DASHBOARD_PASSWORD가 있으면
HTTP Basic 비밀번호를 요구한다(아이디는 무시).
"""
from __future__ import annotations

import csv
import io
import os
from datetime import datetime, timedelta
import subprocess
import sys
from pathlib import Path

from flask import (Flask, Response, jsonify, redirect, render_template_string,
                   request, send_from_directory, url_for)

import db
import scout

ROOT = Path(__file__).resolve().parent
LOG_PATH = db.DATA_DIR / "collect.log"
PORT = int(os.environ.get("PORT") or 8011)
PASSWORD = os.environ.get("DASHBOARD_PASSWORD")

app = Flask(__name__)


@app.before_request
def _auth():
    if PASSWORD:
        a = request.authorization
        if not (a and a.password == PASSWORD):
            return Response("비밀번호가 필요합니다", 401,
                            {"WWW-Authenticate": 'Basic realm="adarchive"'})

PAGE = r"""
<!doctype html>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>경쟁사 광고 아카이브</title>
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<meta name="theme-color" content="#2563eb">
<style>
  :root{
    --bg:#f6f7f9; --panel:#fff; --line:#e3e6ea; --text:#1c1f23;
    --muted:#6b7280; --accent:#2563eb; --accent-soft:#eff4ff;
    --good:#0f9d58; --warn:#b45309;
  }
  @media (prefers-color-scheme: dark){
    :root{ --bg:#14161a; --panel:#1c1f25; --line:#2c3038; --text:#e8eaed;
           --muted:#9aa3ae; --accent:#6ea8fe; --accent-soft:#1e2635; }
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
       font:14px/1.5 "Malgun Gothic","Segoe UI",system-ui,sans-serif}
  header{position:sticky;top:0;z-index:20;background:var(--panel);
         border-bottom:1px solid var(--line);padding:12px 20px;
         display:flex;gap:16px;align-items:center;flex-wrap:wrap}
  h1{font-size:16px;margin:0;font-weight:700;white-space:nowrap}
  .stat{color:var(--muted);font-size:12px}
  .stat b{color:var(--text);font-size:14px}
  main{padding:18px 20px 60px;max-width:1500px;margin:0 auto}
  form.filters{display:flex;gap:8px;flex-wrap:wrap;align-items:center;
        background:var(--panel);border:1px solid var(--line);border-radius:10px;
        padding:12px;margin-bottom:18px}
  input,select,button,textarea{font:inherit;color:var(--text);background:var(--panel);
        border:1px solid var(--line);border-radius:7px;padding:7px 9px}
  input[type=text]{min-width:150px}
  button{cursor:pointer;background:var(--accent);color:#fff;border-color:transparent;
        font-weight:600;padding:7px 14px}
  button.ghost{background:transparent;color:var(--accent);border-color:var(--line);
        font-weight:500}
  .grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(250px,1fr))}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
        overflow:hidden;display:flex;flex-direction:column}
  .thumb{aspect-ratio:1/1;background:#0002;display:flex;align-items:center;
        justify-content:center;overflow:hidden;cursor:pointer}
  .thumb img,.thumb video{width:100%;height:100%;object-fit:cover}
  .thumb .none{color:var(--muted);font-size:12px}
  .body{padding:10px 12px;display:flex;flex-direction:column;gap:6px;flex:1}
  .row{display:flex;gap:6px;align-items:center;flex-wrap:wrap}
  .brand{font-weight:700}
  .tag{font-size:11px;padding:2px 7px;border-radius:99px;background:var(--accent-soft);
        color:var(--accent);white-space:nowrap}
  .tag.on{background:#0f9d5822;color:var(--good)}
  .tag.off{background:#88888822;color:var(--muted)}
  .tag.new{background:#f59e0b22;color:var(--warn)}
  .copy{font-size:12px;color:var(--muted);max-height:60px;overflow:hidden;
        white-space:pre-wrap}
  .meta{font-size:11px;color:var(--muted);margin-top:auto}
  a{color:var(--accent);text-decoration:none}
  .empty{padding:60px 0;text-align:center;color:var(--muted)}
  dialog{border:1px solid var(--line);border-radius:12px;background:var(--panel);
        color:var(--text);max-width:900px;width:92vw;padding:0}
  dialog::backdrop{background:#0009}
  .dlg-head{display:flex;justify-content:space-between;align-items:center;
        padding:14px 18px;border-bottom:1px solid var(--line)}
  .dlg-body{padding:18px;display:grid;grid-template-columns:1fr 1fr;gap:18px}
  .dlg-body img,.dlg-body video{width:100%;border-radius:8px;border:1px solid var(--line)}
  .kv{font-size:13px;margin:0}
  .kv dt{color:var(--muted);font-size:11px;margin-top:10px}
  .kv dd{margin:2px 0 0}
  .pager{display:flex;gap:8px;justify-content:center;margin-top:22px;align-items:center}
  details.run{margin-bottom:18px;background:var(--panel);border:1px solid var(--line);
        border-radius:10px;padding:10px 14px}
  details.run summary{cursor:pointer;font-weight:600}
  pre.log{max-height:200px;overflow:auto;font-size:11px;background:#0001;padding:8px;
        border-radius:6px;white-space:pre-wrap}
  @media (max-width:700px){ .dlg-body{grid-template-columns:1fr} }
</style>

<header>
  <h1>경쟁사 광고 아카이브</h1>
  {{ nav|safe }}
  <span class="stat">총 <b>{{ total }}</b>건</span>
  <span class="stat">활성 <b>{{ active_cnt }}</b></span>
  <span class="stat">최근 7일 신규 <b>{{ new_cnt }}</b></span>
  <span class="stat">브랜드 <b>{{ brands|length }}</b></span>
  <span style="flex:1"></span>
  <a class="tag" href="{{ url_for('export_csv') }}?{{ qs }}">CSV 내보내기</a>
</header>

<main>
  <details class="run">
    <summary>새로 수집하기</summary>
    <form method="post" action="{{ url_for('run_collect') }}" class="row" style="margin-top:10px">
      <input type="text" name="brand" placeholder="브랜드 라벨 (예: 아이베베)" required>
      <input type="text" name="keyword" placeholder="검색 키워드">
      <input type="text" name="page_id" placeholder="또는 페이지 ID">
      <input type="number" name="max" value="100" style="width:90px" title="최대 건수">
      <label class="stat"><input type="checkbox" name="headless" style="vertical-align:-2px"> 창 숨기기</label>
      <button>수집 시작</button>
      <a class="tag" href="{{ url_for('index') }}?{{ qs }}">새로고침</a>
    </form>
    <p class="stat" style="margin:8px 0 0">
      최초 1회는 터미널에서 <code>python collect.py --login</code> 으로 페이스북 로그인이 필요합니다.
    </p>
    {% if log %}<pre class="log">{{ log }}</pre>{% endif %}
  </details>

  <form class="filters" method="get">
    <select name="brand">
      <option value="">전체 브랜드</option>
      {% for b in brands %}
      <option value="{{ b }}" {% if b == f.brand %}selected{% endif %}>{{ b }}</option>
      {% endfor %}
    </select>
    <select name="active">
      <option value="">활성/종료 전체</option>
      <option value="1" {% if f.active=='1' %}selected{% endif %}>진행 중</option>
      <option value="0" {% if f.active=='0' %}selected{% endif %}>종료</option>
    </select>
    <select name="media">
      <option value="">전체 소재</option>
      {% for m in ['video','image','text'] %}
      <option value="{{ m }}" {% if f.media==m %}selected{% endif %}>{{ m }}</option>
      {% endfor %}
    </select>
    <input type="text" name="q" value="{{ f.q }}" placeholder="문구 검색">
    <input type="date" name="from" value="{{ f['from'] }}" title="게재 시작일 이후">
    <input type="date" name="to" value="{{ f.to }}" title="게재 시작일 이전">
    <select name="sort">
      <option value="new" {% if f.sort=='new' %}selected{% endif %}>최근 수집순</option>
      <option value="start" {% if f.sort=='start' %}selected{% endif %}>게재 시작 최신순</option>
      <option value="old" {% if f.sort=='old' %}selected{% endif %}>게재 시작 오래된순</option>
    </select>
    <button>적용</button>
    <a class="tag" href="{{ url_for('index') }}">초기화</a>
  </form>

  {% if ads %}
  <div class="grid">
    {% for a in ads %}
    <div class="card">
      <div class="thumb" onclick="openAd('{{ a.ad_archive_id }}')">
        {% if a.thumb %}
          <img loading="lazy" src="{{ url_for('media_file', path=a.thumb) }}" alt="">
        {% elif a.remote_thumb %}
          <img loading="lazy" src="{{ a.remote_thumb }}" alt="">
        {% else %}
          <span class="none">소재 없음</span>
        {% endif %}
      </div>
      <div class="body">
        <div class="row">
          <span class="brand">{{ a.brand or a.page_name or '-' }}</span>
          {% if a.is_active == 1 %}<span class="tag on">진행중</span>
          {% elif a.is_active == 0 %}<span class="tag off">종료</span>{% endif %}
          {% if a.is_new %}<span class="tag new">NEW</span>{% endif %}
          <span class="tag">{{ a.media_type }}</span>
        </div>
        {% if a.title %}<div style="font-weight:600;font-size:13px">{{ a.title }}</div>{% endif %}
        <div class="copy">{{ a.body or '' }}</div>
        <div class="meta">
          {{ a.start_date or '?' }} ~ {{ a.end_date or '진행' }}
          {% if a.platforms %} · {{ a.platforms }}{% endif %}<br>
          <a href="#" onclick="openAd('{{ a.ad_archive_id }}');return false">자세히</a>
          {% if a.link_url %} · <a href="{{ a.link_url }}" target="_blank" rel="noopener">랜딩</a>{% endif %}
        </div>
      </div>
    </div>
    {% endfor %}
  </div>

  <div class="pager">
    {% if page > 1 %}<a class="tag" href="?{{ qs }}&page={{ page-1 }}">← 이전</a>{% endif %}
    <span class="stat">{{ page }} / {{ pages }}</span>
    {% if page < pages %}<a class="tag" href="?{{ qs }}&page={{ page+1 }}">다음 →</a>{% endif %}
  </div>
  {% else %}
  <div class="empty">
    조건에 맞는 광고가 없습니다.<br>
    위 <b>새로 수집하기</b>로 브랜드를 하나 수집해 보세요.
  </div>
  {% endif %}
</main>

<dialog id="dlg">
  <div class="dlg-head"><b id="dlg-title">광고 상세</b>
    <button class="ghost" onclick="document.getElementById('dlg').close()">닫기</button></div>
  <div class="dlg-body" id="dlg-body"></div>
</dialog>

<script>
async function openAd(id){
  const dlg = document.getElementById('dlg');
  const box = document.getElementById('dlg-body');
  box.innerHTML = '<p>불러오는 중…</p>';
  dlg.showModal();
  const r = await fetch('/api/ad/' + id);
  const a = await r.json();
  document.getElementById('dlg-title').textContent =
        (a.brand || a.page_name || '광고') + ' · ' + id;
  const mediaHtml = (a.media || []).map(m => {
    const src = m.local_path ? ('/media/' + m.local_path) : m.url;
    if (m.kind === 'video') return '<video controls src="' + src + '"></video>';
    return '<img loading="lazy" src="' + src + '">';
  }).join('') || '<p class="stat">저장된 소재 없음</p>';
  const esc = s => (s || '-').toString().replace(/[<>&]/g, c =>
        ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
  box.innerHTML =
    '<div>' + mediaHtml + '</div>' +
    '<dl class="kv">' +
    '<dt>페이지</dt><dd>' + esc(a.page_name) + '</dd>' +
    '<dt>게재 기간</dt><dd>' + esc(a.start_date) + ' ~ ' + (a.end_date || '진행 중') + '</dd>' +
    '<dt>플랫폼</dt><dd>' + esc(a.platforms) + '</dd>' +
    '<dt>제목</dt><dd>' + esc(a.title) + '</dd>' +
    '<dt>본문</dt><dd style="white-space:pre-wrap">' + esc(a.body) + '</dd>' +
    '<dt>CTA</dt><dd>' + esc(a.cta_text) + '</dd>' +
    '<dt>랜딩</dt><dd>' + (a.link_url ? '<a target="_blank" rel="noopener" href="' +
        a.link_url + '">' + esc(a.link_url).slice(0,80) + '</a>' : '-') + '</dd>' +
    '<dt>수집</dt><dd>' + esc(a.first_seen) + ' (최근 확인 ' + esc(a.last_seen) + ')</dd>' +
    '<dt>검색 키워드</dt><dd>' + esc(a.keyword) + '</dd>' +
    '</dl>';
}
</script>
"""

PER_PAGE = 48


def _filters():
    return {
        "brand": request.args.get("brand", ""),
        "active": request.args.get("active", ""),
        "media": request.args.get("media", ""),
        "q": request.args.get("q", ""),
        "from": request.args.get("from", ""),
        "to": request.args.get("to", ""),
        "sort": request.args.get("sort", "new"),
    }


def _where(f):
    sql, args = [], []
    if f["brand"]:
        sql.append("a.brand = ?")
        args.append(f["brand"])
    if f["active"] in ("0", "1"):
        sql.append("a.is_active = ?")
        args.append(int(f["active"]))
    if f["media"]:
        sql.append("a.media_type = ?")
        args.append(f["media"])
    if f["q"]:
        sql.append("(a.body LIKE ? OR a.title LIKE ? OR a.caption LIKE ?)")
        like = "%" + f["q"] + "%"
        args += [like, like, like]
    if f["from"]:
        sql.append("a.start_date >= ?")
        args.append(f["from"])
    if f["to"]:
        sql.append("a.start_date <= ?")
        args.append(f["to"])
    return (" WHERE " + " AND ".join(sql) if sql else ""), args


ORDER = {
    "new": "a.first_seen DESC, a.ad_archive_id DESC",
    "start": "a.start_date DESC NULLS LAST, a.first_seen DESC",
    "old": "a.start_date ASC, a.first_seen DESC",
}


@app.route("/")
def index():
    con = db.connect()
    f = _filters()
    where, args = _where(f)
    order = ORDER.get(f["sort"], ORDER["new"])
    page = max(1, int(request.args.get("page", 1)))

    total_f = con.execute("SELECT COUNT(*) c FROM ads a" + where, args).fetchone()["c"]
    rows = con.execute(
        "SELECT a.* FROM ads a" + where + " ORDER BY " + order + " LIMIT ? OFFSET ?",
        args + [PER_PAGE, (page - 1) * PER_PAGE]).fetchall()

    ads = []
    for r in rows:
        d = dict(r)
        thumb = con.execute(
            "SELECT local_path, url, kind FROM media WHERE ad_archive_id=? "
            "ORDER BY CASE kind WHEN 'image' THEN 0 WHEN 'thumb' THEN 1 ELSE 2 END, id",
            (r["ad_archive_id"],)).fetchone()
        d["thumb"] = (thumb["local_path"]
                      if thumb and thumb["local_path"] not in (None, "", "FAILED")
                      else None)
        d["remote_thumb"] = (thumb["url"] if thumb and not d["thumb"]
                             and thumb["kind"] != "video" else None)
        d["is_new"] = bool(con.execute(
            "SELECT 1 FROM ads WHERE ad_archive_id=? AND first_seen >= "
            "datetime('now','-7 days')", (r["ad_archive_id"],)).fetchone())
        ads.append(d)

    brands = [r["brand"] for r in con.execute(
        "SELECT DISTINCT brand FROM ads WHERE brand IS NOT NULL AND brand<>'' "
        "ORDER BY brand").fetchall()]
    total = con.execute("SELECT COUNT(*) c FROM ads").fetchone()["c"]
    active_cnt = con.execute("SELECT COUNT(*) c FROM ads WHERE is_active=1").fetchone()["c"]
    new_cnt = con.execute("SELECT COUNT(*) c FROM ads WHERE first_seen >= "
                          "datetime('now','-7 days')").fetchone()["c"]
    con.close()

    qs = "&".join("%s=%s" % (k, v) for k, v in f.items() if v)
    log = ""
    if LOG_PATH.exists():
        log = "\n".join(LOG_PATH.read_text(encoding="utf-8", errors="replace")
                        .splitlines()[-25:])

    return render_template_string(
        PAGE, nav=nav("archive"), ads=ads, brands=brands, f=f, qs=qs, page=page,
        pages=max(1, -(-total_f // PER_PAGE)), total=total,
        active_cnt=active_cnt, new_cnt=new_cnt, log=log)


@app.route("/api/ad/<ad_id>")
def api_ad(ad_id):
    con = db.connect()
    row = con.execute("SELECT * FROM ads WHERE ad_archive_id=?", (ad_id,)).fetchone()
    if not row:
        # 아카이브(소재 저장) 대상이 아닌 정찰 광고 — 텍스트와 썸네일만 있다
        srow = con.execute("SELECT * FROM scout_ads WHERE ad_archive_id=?", (ad_id,)).fetchone()
        con.close()
        if not srow:
            return jsonify({"error": "not found"}), 404
        d = dict(srow)
        d["keyword"] = d.pop("keywords", "")
        d["media"] = ([{"kind": "image", "url": d["thumb_url"], "local_path": None}]
                      if d.get("thumb_url") else [])
        d["archived"] = False
        return jsonify(d)
    d = dict(row)
    d.pop("raw", None)
    d["archived"] = True
    d["media"] = [
        {"kind": m["kind"], "url": m["url"],
         "local_path": (m["local_path"] if m["local_path"] not in (None, "", "FAILED") else None)}
        for m in con.execute(
            "SELECT kind, url, local_path FROM media WHERE ad_archive_id=? ORDER BY id",
            (ad_id,)).fetchall()]
    con.close()
    return jsonify(d)


@app.route("/media/<path:path>")
def media_file(path):
    return send_from_directory(db.MEDIA_DIR, path)


@app.route("/export.csv")
def export_csv():
    con = db.connect()
    f = _filters()
    where, args = _where(f)
    rows = con.execute(
        "SELECT ad_archive_id, brand, page_name, keyword, is_active, start_date, "
        "end_date, platforms, media_type, title, body, cta_text, link_url, "
        "first_seen FROM ads a" + where + " ORDER BY first_seen DESC", args).fetchall()
    con.close()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["광고ID", "브랜드", "페이지명", "키워드", "진행중", "시작일", "종료일",
                "플랫폼", "소재유형", "제목", "본문", "CTA", "랜딩URL", "수집일"])
    for r in rows:
        w.writerow(list(r))
    return Response(
        "﻿" + buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=competitor_ads.csv"})


@app.route("/run", methods=["POST"])
def run_collect():
    brand = (request.form.get("brand") or "").strip()
    keyword = (request.form.get("keyword") or "").strip()
    page_id = (request.form.get("page_id") or "").strip()
    max_ads = request.form.get("max") or "100"
    if not brand or not (keyword or page_id):
        return redirect(url_for("index"))

    cmd = [sys.executable, str(ROOT / "collect.py"), "--brand", brand,
           "--max", str(int(max_ads))]
    if keyword:
        cmd += ["--keyword", keyword]
    if page_id:
        cmd += ["--page-id", page_id]
    if request.form.get("headless") or not os.environ.get("DISPLAY"):
        cmd += ["--headless"]   # 서버에는 화면이 없다

    logf = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    logf.write("\n$ " + " ".join(cmd) + "\n")
    subprocess.Popen(cmd, cwd=str(ROOT), stdout=logf, stderr=logf,
                     stdin=subprocess.DEVNULL)
    return redirect(url_for("index"))


# ================================================================ 정찰·리포트·경쟁사
# 기존 아카이브 화면의 <style>을 그대로 쓴다.
HEAD = PAGE[:PAGE.index("<header>")]
DIALOG = PAGE[PAGE.index('<dialog id="dlg">'):]

NAV_ITEMS = [("report", "리포트"), ("scout_view", "정찰"),
             ("brands_view", "경쟁사"), ("index", "아카이브")]


def nav(active):
    out = ['<nav class="row" style="gap:4px">']
    for ep, label in NAV_ITEMS:
        cls = "tag" if ep == active or (active == "archive" and ep == "index") else "tag off"
        out.append('<a class="%s" href="%s">%s</a>' % (cls, url_for(ep), label))
    out.append("</nav>")
    return "".join(out)


EXTRA_CSS = """<style>
  table.t{border-collapse:collapse;width:100%;font-size:13px;background:var(--panel)}
  table.t th,table.t td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;
        vertical-align:top}
  table.t th{color:var(--muted);font-weight:600;font-size:12px}
  .num{text-align:right!important;font-variant-numeric:tabular-nums}
  .sec{background:var(--panel);border:1px solid var(--line);border-radius:10px;
       padding:14px 16px;margin-bottom:16px}
  .sec h2{font-size:15px;margin:0 0 10px}
  .sec h3{font-size:13px;margin:14px 0 6px;color:var(--muted)}
  .tw{overflow-x:auto}
  .up{color:var(--good)} .down{color:#dc2626}
  .chips{display:flex;gap:6px;flex-wrap:wrap}
  .note{font-size:12px;color:var(--warn);margin:0 0 12px}
  form.inline{display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap}
</style>"""

REPORT_PAGE = HEAD + EXTRA_CSS + r"""
<header>
  <h1>경쟁사 광고 리포트</h1>
  {{ nav|safe }}
  <span style="flex:1"></span>
  <form method="get" class="inline">
    <select name="date" onchange="this.form.submit()">
      {% for d in dates %}<option {% if rep and d==rep.date %}selected{% endif %}>{{ d }}</option>{% endfor %}
    </select>
  </form>
</header>
<main>
{% if not rep %}
  <div class="empty">아직 리포트가 없습니다. 매일 아침 07:30에 만들어집니다.</div>
{% else %}
  {% if rep.baseline_days < 7 %}
  <p class="note">정찰 {{ rep.baseline_days + 1 }}일째입니다. 추이와 "처음 포착" 항목은 7일이 쌓여야 믿을 만합니다
  (첫날엔 모든 광고주가 '처음 본 곳'으로 잡힙니다).</p>
  {% endif %}
  {% if rep.discovered %}
  <div class="sec"><h2>★ 오늘 자동 발견</h2>
    <table class="t">{% for k in rep.discovered %}
      <tr><td>{{ k.brand }}</td><td>{{ '새 계정' if k.kind=='page' else '새 도메인' }}</td>
      <td>{% if k.kind=='page' %}<a href="{{ url_for('scout_view', page=k.value) }}">{{ k.label or k.value }}</a>{% else %}{{ k.value }}{% endif %}</td></tr>
    {% endfor %}</table></div>
  {% endif %}

  {% for c in rep.categories %}
  <div class="sec">
    <h2>{{ c.name }} {% if c.ours %}<span class="stat">우리: {{ c.ours }}</span>{% endif %}
      <span class="stat"> · 신규 광고 <b>{{ c.new_ads }}</b>건</span></h2>

    {% if c.competitors %}
    <h3>등록 경쟁사</h3>
    <div class="tw"><table class="t">
      <tr><th>브랜드</th><th class="num">게재 중(포착)</th><th class="num">오늘 신규</th>
          <th class="num">아카이브 신규</th><th class="num">계정 수</th><th></th></tr>
      {% for b in c.competitors %}
      <tr><td><b><a href="{{ url_for('brands_view', brand=b.brand) }}">{{ b.brand }}</a></b></td><td class="num">{{ b.active_ads }}</td>
        <td class="num">{{ b.new_ads }}</td><td class="num">{{ b.archived_new }}</td>
        <td class="num">{{ b.pages }}</td>
        <td><a href="{{ url_for('brands_view', brand=b.brand) }}">광고 보기</a></td></tr>
      {% endfor %}
    </table></div>
    {% endif %}

    <h3>시장 — 키워드별 광고 수</h3>
    <div class="tw"><table class="t">
      <tr><th>키워드</th><th class="num">게재 중</th><th class="num">7일 전 대비</th>
          <th class="num">어제 시작(포착)</th><th class="num">7일 일평균(포착)</th></tr>
      {% for k in c.keywords %}
      <tr><td>{{ k.keyword }}</td><td class="num">{{ fmt(k.active) }}</td>
        <td class="num">{% if k.active is not none and k.active_7d_ago %}
          {% set p = (k.active - k.active_7d_ago) / k.active_7d_ago * 100 %}
          <span class="{{ 'up' if p >= 0 else 'down' }}">{{ '%+.0f'|format(p) }}%</span>{% else %}-{% endif %}</td>
        <td class="num">{{ fmt(k.started_yesterday) }}</td><td class="num">{{ fmt(k.started_avg_7d) }}</td></tr>
      {% endfor %}
    </table></div>

    {% if c.top %}
    <h3>오늘 광고를 많이 낸 곳 (랜딩 기준)</h3>
    <div class="tw"><table class="t">
      <tr><th>브랜드/랜딩</th><th class="num">신규</th><th>계정명(위장 포함)</th><th></th></tr>
      {% for t in c.top %}
      <tr><td>{% if t.known %}<b>{{ t.who }}</b> ★{% else %}{{ t.who }}{% endif %}</td>
        <td class="num">{{ t.new_ads }}</td><td>{{ t.pages|join(', ') }}</td>
        <td>{% if t.known %}<a href="{{ url_for('brands_view', brand=t.who) }}">광고 보기</a>{% elif t.landing %}<a href="{{ url_for('scout_view', landing=t.landing) }}">광고 보기</a>{% else %}<a href="{{ url_for('scout_view', q=t.pages[0]) }}">광고 보기</a>{% endif %}</td></tr>
      {% endfor %}
    </table></div>
    {% endif %}

    {% if c.new_landings %}
    <h3>처음 포착한 랜딩 — 신규 브랜드 후보</h3>
    <div class="tw"><table class="t">
      <tr><th>랜딩</th><th class="num">광고</th><th>첫 게재</th><th>계정명</th><th>문구</th><th></th></tr>
      {% for b in c.new_landings %}
      <tr><td>{{ b.landing }}</td><td class="num">{{ b.ads }}</td><td>{{ b.first_start }}</td>
        <td>{{ b.pages[:3]|join(', ') }}</td><td class="stat">{{ b.sample[:70] }}</td>
        <td><a href="{{ url_for('scout_view', landing=b.landing) }}">광고 보기</a></td></tr>
      {% endfor %}
    </table></div>
    {% endif %}

    {% if c.words %}
    <h3>신규 광고에 많이 쓴 표현 <span class="stat">숫자 = 그 표현을 쓴 광고주 수 · ↑ = 지난 4주보다 급증</span></h3>
    <div class="chips">{% for w in c.words %}
      <span class="tag {{ 'new' if w.rising else '' }}">{{ w.word }} {{ w.ads }}{{ ' ↑' if w.rising else '' }}</span>
    {% endfor %}</div>
    {% endif %}

    {% if c.samples %}
    <h3>신규 광고 예시 <a class="stat" href="{{ url_for('scout_view', category=c.name, fresh=1) }}">전체 보기 →</a></h3>
    <div class="grid">{% for a in c.samples %}
      <div class="card">
        <div class="thumb" onclick="openAd('{{ a.id or a.library.split('id=')[-1] }}')">
          {% if a.thumb_url %}<img loading="lazy" src="{{ a.thumb_url }}" alt="">{% else %}<span class="none">{{ a.media_type }}</span>{% endif %}</div>
        <div class="body"><span class="brand">{{ a.who }}</span>
          <span class="stat">{{ a.page_name }} · {{ a.start_date }}</span>
          <div class="copy">{{ a.text }}</div></div>
      </div>
    {% endfor %}</div>
    {% endif %}
  </div>
  {% endfor %}
  <p class="stat">생성 {{ rep.generated_at }}</p>
{% endif %}
</main>
""" + DIALOG


def _fmt(n):
    return "-" if n is None else "{:,}".format(int(round(n)))


def local_thumbs(con, ids):
    """아카이브에 저장된 광고는 서버 파일 썸네일을 쓴다 — 페이스북 이미지 주소는 며칠 뒤 만료된다."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    out = {}
    for r in con.execute(
            "SELECT ad_archive_id, local_path, kind FROM media WHERE ad_archive_id IN (%s) "
            "AND local_path NOT IN ('', 'FAILED') AND kind IN ('image','thumb') "
            "ORDER BY CASE kind WHEN 'image' THEN 0 ELSE 1 END, id" % ",".join("?" * len(ids)),
            ids):
        out.setdefault(r["ad_archive_id"], url_for("media_file", path=r["local_path"]))
    return out


@app.route("/report")
def report():
    dates = sorted((p.stem for p in db.REPORT_DIR.glob("????-??-??.json")), reverse=True)
    rep = scout.load_report(request.args.get("date") or None)
    if rep:
        con = db.connect()
        ids = [a.get("id") or a["library"].split("id=")[-1]
               for c in rep["categories"] for a in c["samples"]]
        local = local_thumbs(con, ids)
        con.close()
        for c in rep["categories"]:
            for a in c["samples"]:
                lid = local.get(a.get("id") or a["library"].split("id=")[-1])
                if lid:
                    a["thumb_url"] = lid
    return render_template_string(REPORT_PAGE, nav=nav("report"), rep=rep, dates=dates,
                                  fmt=_fmt, page_link=scout.page_link)


SCOUT_PAGE = HEAD + EXTRA_CSS + r"""
<header>
  <h1>카테고리 정찰</h1>
  {{ nav|safe }}
  <span class="stat">조건 <b>{{ total }}</b>건</span>
</header>
<main>
  <form class="filters" method="get">
    <select name="category"><option value="">전체 카테고리</option>
      {% for c in categories %}<option {% if c==f.category %}selected{% endif %}>{{ c }}</option>{% endfor %}</select>
    <select name="who"><option value="">전체 광고주</option>
      <option value="_known" {% if f.who=='_known' %}selected{% endif %}>등록 경쟁사만</option>
      <option value="_unknown" {% if f.who=='_unknown' %}selected{% endif %}>미등록만</option>
      {% for b in brand_names %}<option {% if b==f.who %}selected{% endif %}>{{ b }}</option>{% endfor %}</select>
    <input type="text" name="landing" value="{{ f.landing }}" placeholder="랜딩 도메인">
    <input type="text" name="q" value="{{ f.q }}" placeholder="문구·계정명 검색">
    <label class="stat"><input type="checkbox" name="fresh" value="1" {% if f.fresh %}checked{% endif %}> 오늘 처음 본 것만</label>
    <button>적용</button>
    <a class="tag" href="{{ url_for('scout_view') }}">초기화</a>
  </form>
  <datalist id="brandlist">{% for b in brand_names %}<option value="{{ b }}">{% endfor %}</datalist>
  {% if ads %}
  <div class="grid">{% for a in ads %}
    <div class="card">
      <div class="thumb" onclick="openAd('{{ a.ad_archive_id }}')">
        {% if a.thumb_url %}<img loading="lazy" src="{{ a.thumb_url }}" alt="">{% else %}<span class="none">{{ a.media_type }}</span>{% endif %}</div>
      <div class="body">
        <div class="row"><span class="brand">{{ a.brand or a.landing or '-' }}</span>
          {% if a.saved %}<span class="tag on">저장됨</span>{% elif a.brand %}<span class="tag">등록</span>{% endif %}
          <span class="tag">{{ a.media_type }}</span></div>
        <span class="stat">{{ a.page_name }} · {{ a.start_date }}</span>
        {% if a.title %}<div style="font-weight:600;font-size:13px">{{ a.title }}</div>{% endif %}
        <div class="copy">{{ a.body or '' }}</div>
        <div class="meta">
          <a href="{{ url_for('scout_view', page=a.page_id) }}">이 계정 광고 전체</a>
          {% if a.link_url %} · <a target="_blank" rel="noopener" href="{{ a.link_url }}">랜딩</a>{% endif %}
          {% if a.brand != '(우리)' %}
          <form method="post" action="{{ url_for('brand_attach') }}" class="inline" style="margin-top:6px">
            <input type="hidden" name="page_id" value="{{ a.page_id }}">
            <input type="hidden" name="page_name" value="{{ a.page_name }}">
            <input type="hidden" name="landing" value="{{ a.landing or '' }}">
            <input type="hidden" name="category" value="{{ a.category }}">
            <input type="hidden" name="back" value="{{ request.full_path }}">
            <input type="text" name="brand" list="brandlist" value="{{ a.brand or '' }}"
                   placeholder="브랜드명" style="min-width:0;width:110px" required>
            <button class="ghost" title="이 계정(과 랜딩 도메인)을 경쟁사로 등록하고 소재까지 아카이브">아카이브</button>
          </form>{% endif %}
        </div>
      </div>
    </div>{% endfor %}</div>
  <div class="pager">
    {% if page > 1 %}<a class="tag" href="?{{ qs }}&p={{ page-1 }}">← 이전</a>{% endif %}
    <span class="stat">{{ page }} / {{ pages }}</span>
    {% if page < pages %}<a class="tag" href="?{{ qs }}&p={{ page+1 }}">다음 →</a>{% endif %}
  </div>
  {% else %}<div class="empty">조건에 맞는 광고가 없습니다.</div>{% endif %}
</main>
""" + DIALOG


@app.route("/scout")
def scout_view():
    f = {k: request.args.get(k, "") for k in ("category", "who", "landing", "q", "fresh", "page")}
    sql, args = [], []
    if f["category"]:
        sql.append("category=?"); args.append(f["category"])
    if f["who"] == "_known":
        sql.append("IFNULL(brand,'') NOT IN ('', '(우리)')")
    elif f["who"] == "_unknown":
        sql.append("IFNULL(brand,'')=''")
    elif f["who"]:
        sql.append("brand=?"); args.append(f["who"])
    if f["landing"]:
        sql.append("landing LIKE ?"); args.append("%" + f["landing"] + "%")
    if f["page"]:
        sql.append("page_id=?"); args.append(f["page"])
    if f["q"]:
        like = "%" + f["q"] + "%"
        sql.append("(body LIKE ? OR title LIKE ? OR page_name LIKE ?)"); args += [like] * 3
    if f["fresh"]:
        sql.append("substr(first_seen,1,10)=date('now','localtime')")
    where = (" WHERE " + " AND ".join(sql)) if sql else ""
    page = max(1, int(request.args.get("p", 1)))
    con = db.connect()
    total = con.execute("SELECT COUNT(*) c FROM scout_ads" + where, args).fetchone()["c"]
    ads = [dict(r) for r in con.execute(
        "SELECT * FROM scout_ads" + where + " ORDER BY start_date DESC, first_seen DESC "
        "LIMIT ? OFFSET ?", args + [PER_PAGE, (page - 1) * PER_PAGE])]
    brand_names = [r["name"] for r in con.execute("SELECT name FROM brands ORDER BY name")]
    local = local_thumbs(con, [a["ad_archive_id"] for a in ads])
    for a in ads:
        a["thumb_url"] = local.get(a["ad_archive_id"]) or a["thumb_url"]
        a["saved"] = a["ad_archive_id"] in local
    con.close()
    categories = [c["name"] for c in scout.load_config()["categories"]]
    qs = "&".join("%s=%s" % (k, v) for k, v in f.items() if v)
    return render_template_string(
        SCOUT_PAGE, nav=nav("scout_view"), ads=ads, f=f, total=total, qs=qs, page=page,
        pages=max(1, -(-total // PER_PAGE)), brand_names=brand_names,
        categories=categories, page_link=scout.page_link)


@app.route("/brand/attach", methods=["POST"])
def brand_attach():
    """정찰 카드의 '아카이브' 버튼: 계정(+랜딩 도메인)을 브랜드에 묶고 아카이브 대상으로."""
    fm = request.form
    name = (fm.get("brand") or "").strip()
    if name and name != "(우리)":
        con = db.connect()
        scout.add_brand(con, name, fm.get("category") or None,
                        pages=[fm.get("page_id")] if fm.get("page_id") else [],
                        domains=[fm.get("landing")] if fm.get("landing") else [],
                        source="web")
        con.execute("UPDATE brand_keys SET label=COALESCE(label, ?) WHERE kind='page' "
                    "AND value=?", (fm.get("page_name"), fm.get("page_id")))
        con.execute("UPDATE scout_ads SET brand=? WHERE page_id=? OR "
                    "(landing<>'' AND landing=?)", (name, fm.get("page_id"), fm.get("landing")))
        con.commit()
        con.close()
    back = fm.get("back") or url_for("scout_view")
    return redirect(back if back.startswith("/") else url_for("scout_view"))


BRANDS_CSS = """<style>
  .tiles{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
         margin-bottom:20px}
  .tile{background:var(--panel);border:1px solid var(--line);border-radius:12px;
        overflow:hidden;color:var(--text);display:flex;flex-direction:column}
  .tile:hover{border-color:var(--accent)}
  .tile.on{border:2px solid var(--accent)}
  .tile .cover{aspect-ratio:16/9;background:#0002;overflow:hidden}
  .tile .cover img{width:100%;height:100%;object-fit:cover}
  .tile .tb{padding:10px 12px}
  .tile .nm{font-weight:700;font-size:15px}
  .tile .nums{display:flex;gap:10px;font-size:12px;color:var(--muted);margin-top:4px;flex-wrap:wrap}
  .tile .nums b{color:var(--text)}
  .adgrid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(290px,1fr))}
  .ad{background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;
      display:flex;flex-direction:column}
  .ad .m{background:#000;aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;
         overflow:hidden;min-height:0}
  .ad .m img,.ad .m video{width:100%;height:100%;object-fit:contain;background:#000}
  .ad .info{padding:10px 12px;display:flex;flex-direction:column;gap:6px;font-size:12px}
  .facts{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;margin:0}
  .facts dt{color:var(--muted)} .facts dd{margin:0}
  .ad .ttl{font-weight:700;font-size:13px}
  .ad details.cp summary{list-style:none;cursor:pointer}
  .ad details.cp summary::-webkit-details-marker{display:none}
  .ad .clamp{white-space:pre-wrap;display:-webkit-box;-webkit-line-clamp:5;
             -webkit-box-orient:vertical;overflow:hidden}
  .ad details[open] .clamp{-webkit-line-clamp:unset;display:block}
  .ad .more{color:var(--accent);font-size:11px}
  .seg{display:flex;gap:6px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
</style>"""

BRANDS_PAGE = HEAD + EXTRA_CSS + BRANDS_CSS + r"""
<header>
  <h1>경쟁사</h1>
  {{ nav|safe }}
</header>
<main>
  <div class="tiles">
    {% for b in tiles %}
    <a class="tile {{ 'on' if sel and sel.name == b.name else '' }}" href="{{ url_for('brands_view', brand=b.name) }}">
      <div class="cover">{% if b.cover %}<img loading="lazy" src="{{ b.cover }}" alt="">{% endif %}</div>
      <div class="tb">
        <div class="nm">{{ b.name }}</div>
        <div class="nums"><span>게재 중 <b>{{ b.active }}</b></span><span>저장 <b>{{ b.total }}</b></span>
          <span>7일 신규 <b>{{ b.new7 }}</b></span></div>
        <div class="nums"><span>최근 게시 {{ b.latest or '-' }}</span><span>계정 {{ b.pages }}</span></div>
      </div>
    </a>
    {% else %}<div class="empty">아카이브 중인 브랜드가 없습니다.</div>{% endfor %}
  </div>

  {% if sel %}
  <div class="sec">
    <h2>{{ sel.name }} <span class="stat">{{ sel.category or '' }} · 계정: {{ sel.labels|join(', ') }}</span></h2>
    {% if sel.note %}<p class="stat" style="margin:0 0 10px">{{ sel.note }}</p>{% endif %}
    <form class="seg" method="get">
      <input type="hidden" name="brand" value="{{ sel.name }}">
      <select name="status" onchange="this.form.submit()">
        <option value="">전체 {{ counts.all }}</option>
        <option value="1" {% if status=='1' %}selected{% endif %}>게재 중 {{ counts.on }}</option>
        <option value="0" {% if status=='0' %}selected{% endif %}>종료 {{ counts.off }}</option>
      </select>
      <select name="media" onchange="this.form.submit()">
        <option value="">전체 소재</option>
        <option value="video" {% if media=='video' %}selected{% endif %}>영상</option>
        <option value="image" {% if media=='image' %}selected{% endif %}>이미지</option>
      </select>
      <select name="sort" onchange="this.form.submit()">
        <option value="new" {% if sort=='new' %}selected{% endif %}>게시일 최신순</option>
        <option value="long" {% if sort=='long' %}selected{% endif %}>오래 돈 순(성과 추정)</option>
      </select>
      <span class="stat">{{ ads|length }}건</span>
    </form>
    <div class="adgrid">
      {% for a in ads %}
      <div class="ad">
        <div class="m">
          {% if a.video %}<video controls preload="none" {% if a.poster %}poster="{{ a.poster }}"{% endif %} src="{{ a.video }}"></video>
          {% elif a.image %}<img loading="lazy" src="{{ a.image }}" alt="" onclick="openAd('{{ a.ad_archive_id }}')" style="cursor:zoom-in">
          {% else %}<span class="none">소재 없음</span>{% endif %}
        </div>
        <div class="info">
          <div class="row">
            {% if a.is_active == 1 %}<span class="tag on">게재 중</span>{% else %}<span class="tag off">종료</span>{% endif %}
            <span class="tag">{{ {'video':'영상','image':'이미지','text':'텍스트'}.get(a.media_type, a.media_type) }}</span>
            {% if a.n_media > 1 %}<span class="tag">소재 {{ a.n_media }}개</span>{% endif %}
            {% if a.is_new %}<span class="tag new">NEW</span>{% endif %}
          </div>
          <dl class="facts">
            <dt>게시일</dt><dd><b>{{ a.start_date or '?' }}</b>{% if a.days is not none %} · {{ a.days }}일째{% endif %}</dd>
            <dt>{{ '종료' if a.is_active != 1 else '확인' }}</dt><dd>{{ a.end_shown }}</dd>
            <dt>계정</dt><dd>{{ a.page_name or '-' }}</dd>
            <dt>채널</dt><dd>{{ a.platforms_ko }}</dd>
            {% if a.cta_text %}<dt>CTA</dt><dd>{{ a.cta_text }}</dd>{% endif %}
            {% if a.landing %}<dt>랜딩</dt><dd>{% if a.link_url %}<a href="{{ a.link_url }}" target="_blank" rel="noopener">{{ a.landing }}</a>{% else %}{{ a.landing }}{% endif %}</dd>{% endif %}
          </dl>
          {% if a.title %}<div class="ttl">{{ a.title }}</div>{% endif %}
          {% if a.body %}<details class="cp"><summary><div class="clamp">{{ a.body }}</div>
            <span class="more">전체 문구</span></summary></details>{% endif %}
        </div>
      </div>
      {% else %}<div class="empty">조건에 맞는 광고가 없습니다.</div>{% endfor %}
    </div>
  </div>
  {% endif %}

  <details class="run">
    <summary>경쟁사 관리 (추가 · 계정/도메인 · 아카이브 켜고 끄기)</summary>
    <div class="sec" style="margin-top:12px"><h2>경쟁사 추가</h2>
      <form method="post" action="{{ url_for('brand_add') }}" class="inline">
        <input type="text" name="name" placeholder="브랜드명" required>
        <select name="category">{% for c in categories %}<option>{{ c }}</option>{% endfor %}</select>
        <input type="text" name="page" placeholder="메타 페이지 ID">
        <input type="text" name="domain" placeholder="랜딩 도메인 (예: alpha-i.kr)">
        <input type="text" name="term" placeholder="정확히 일치 검색어">
        <button>추가</button>
      </form>
      <p class="stat" style="margin:8px 0 0">페이지 ID는 광고 라이브러리 주소의 <code>view_all_page_id=</code> 뒤 숫자.
      계정명은 위장하므로 <b>랜딩 도메인</b>을 넣어 두면 새 위장 계정이 자동으로 묶입니다.</p>
    </div>
    {% for b in brands %}
    <div class="sec">
      <h2>{{ b.name }} <span class="stat">{{ b.category or '' }} · 저장 {{ b.archived }}건</span>
        <form method="post" action="{{ url_for('brand_toggle') }}" class="inline" style="float:right">
          <input type="hidden" name="name" value="{{ b.name }}">
          <button class="{{ '' if b.archive else 'ghost' }}" name="archive" value="{{ 0 if b.archive else 1 }}">
            {{ '아카이브 중 (끄기)' if b.archive else '아카이브 꺼짐 (켜기)' }}</button></form></h2>
      <div class="tw"><table class="t">
        <tr><th>종류</th><th>값</th><th>이름</th><th>출처</th><th>등록</th></tr>
        {% for k in keys[b.name] %}
        <tr><td>{{ {'page':'계정','domain':'도메인','term':'검색어'}[k.kind] }}</td>
          <td>{% if k.kind=='page' %}<a href="{{ url_for('scout_view', page=k.value) }}">{{ k.value }}</a>{% else %}{{ k.value }}{% endif %}</td>
          <td>{{ k.label or '' }}</td>
          <td>{% if k.source=='auto' %}<span class="tag new">자동 발견</span>{% else %}{{ k.source }}{% endif %}</td>
          <td class="stat">{{ (k.added_at or '')[:10] }}</td></tr>
        {% endfor %}
      </table></div>
      {% if b.google_advertiser %}<p class="stat" style="margin:8px 0 0">구글:
        <a target="_blank" rel="noopener" href="https://adstransparency.google.com/advertiser/{{ b.google_advertiser }}?region=KR">광고 투명성 센터</a></p>{% endif %}
    </div>
    {% endfor %}
  </details>
</main>
""" + DIALOG

PLATFORM_KO = {"FACEBOOK": "페이스북", "INSTAGRAM": "인스타그램", "AUDIENCE_NETWORK": "오디언스 네트워크",
               "MESSENGER": "메신저", "THREADS": "스레드", "WHATSAPP": "왓츠앱"}


def _media_url(path):
    return url_for("media_file", path=path) if path and path != "FAILED" else None


@app.route("/brands")
def brands_view():
    con = db.connect()
    brands = scout.brand_rows(con)
    keys = {b["name"]: [dict(r) for r in con.execute(
        "SELECT * FROM brand_keys WHERE brand=? ORDER BY kind, added_at", (b["name"],))]
        for b in brands}

    # 맨 위: 아카이브 중인 브랜드 타일
    tiles = []
    for b in brands:
        if not b["archive"]:
            continue
        st = con.execute(
            "SELECT COUNT(*) total, SUM(is_active=1) active, MAX(start_date) latest, "
            "SUM(first_seen >= datetime('now','localtime','-7 days')) new7 "
            "FROM ads WHERE brand=?", (b["name"],)).fetchone()
        cov = con.execute(
            "SELECT m.local_path FROM media m JOIN ads a ON a.ad_archive_id=m.ad_archive_id "
            "WHERE a.brand=? AND m.kind IN ('image','thumb') AND m.local_path NOT IN ('','FAILED') "
            "ORDER BY a.start_date DESC LIMIT 1", (b["name"],)).fetchone()
        tiles.append({"name": b["name"], "total": st["total"] or 0, "active": st["active"] or 0,
                      "latest": st["latest"], "new7": st["new7"] or 0, "pages": b["pages"],
                      "cover": _media_url(cov["local_path"]) if cov else None})
    tiles.sort(key=lambda t: (-(t["active"]), t["name"]))

    sel, ads, counts = None, [], {}
    status, media, sort = (request.args.get("status", ""), request.args.get("media", ""),
                           request.args.get("sort", "new"))
    name = request.args.get("brand")
    if not name and tiles:
        name = tiles[0]["name"]
    if name:
        b = next((x for x in brands if x["name"] == name), None)
        if b:
            sel = dict(b)
            sel["labels"] = [k["label"] or k["value"] for k in keys[name] if k["kind"] == "page"]
            c = con.execute("SELECT COUNT(*) a, SUM(is_active=1) o FROM ads WHERE brand=?",
                            (name,)).fetchone()
            counts = {"all": c["a"] or 0, "on": c["o"] or 0, "off": (c["a"] or 0) - (c["o"] or 0)}
            where, args = ["brand=?"], [name]
            if status in ("0", "1"):
                where.append("IFNULL(is_active,0)=?"); args.append(int(status))
            if media:
                where.append("media_type=?"); args.append(media)
            order = ("start_date DESC, first_seen DESC" if sort != "long"
                     else "julianday(COALESCE(end_date, date('now','localtime'))) - julianday(start_date) DESC")
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM ads WHERE " + " AND ".join(where) + " ORDER BY " + order + " LIMIT 400", args)]
            today = datetime.now().date()
            for a in rows:
                a.pop("raw", None)
                ms = [dict(m) for m in con.execute(
                    "SELECT kind, local_path FROM media WHERE ad_archive_id=? AND local_path NOT IN ('','FAILED') "
                    "ORDER BY id", (a["ad_archive_id"],))]
                a["video"] = next((_media_url(m["local_path"]) for m in ms if m["kind"] == "video"), None)
                a["poster"] = next((_media_url(m["local_path"]) for m in ms if m["kind"] == "thumb"), None)
                a["image"] = next((_media_url(m["local_path"]) for m in ms if m["kind"] == "image"), None) or a["poster"]
                a["n_media"] = sum(1 for m in ms if m["kind"] in ("video", "image"))
                end = a["end_date"] if a["is_active"] != 1 else None
                end = end or (a["last_seen"] or "")[:10] if a["is_active"] != 1 else None
                try:
                    s0 = datetime.strptime(a["start_date"], "%Y-%m-%d").date()
                    e0 = datetime.strptime(end, "%Y-%m-%d").date() if end else today
                    a["days"] = (e0 - s0).days + 1
                except Exception:
                    a["days"] = None
                a["end_shown"] = (end or "-") if a["is_active"] != 1 else "게재 중 (마지막 확인 %s)" % (a["last_seen"] or "")[5:16]
                a["platforms_ko"] = ", ".join(PLATFORM_KO.get(p, p.title()) for p in (a["platforms"] or "").split(",") if p) or "-"
                a["landing"] = scout._host(a["link_url"]) if a["link_url"] else None
                a["is_new"] = (a["first_seen"] or "") >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            ads = rows
    con.close()
    categories = [c["name"] for c in scout.load_config()["categories"]]
    return render_template_string(BRANDS_PAGE, nav=nav("brands_view"), brands=brands, keys=keys,
                                  categories=categories, tiles=tiles, sel=sel, ads=ads,
                                  counts=counts, status=status, media=media, sort=sort)


@app.route("/brands/add", methods=["POST"])
def brand_add():
    fm = request.form
    name = (fm.get("name") or "").strip()
    if name:
        con = db.connect()
        one = lambda k: [fm.get(k).strip()] if (fm.get(k) or "").strip() else []
        scout.add_brand(con, name, fm.get("category") or None, one("page"),
                        one("domain"), one("term"), source="web")
        con.close()
    return redirect(url_for("brands_view"))


@app.route("/brands/toggle", methods=["POST"])
def brand_toggle():
    con = db.connect()
    con.execute("UPDATE brands SET archive=? WHERE name=?",
                (int(request.form.get("archive") or 0), request.form.get("name")))
    con.commit()
    con.close()
    return redirect(url_for("brands_view"))


# ---------------------------------------------------------------- PC 앱 설치용
# 크롬 메뉴 → 저장 및 공유 → 바로가기 만들기(창으로 열기)로 바탕화면 아이콘을 만든다.
# 자체서명 인증서라 정식 PWA 설치는 안 될 수 있어서, 이름·아이콘만 제공한다.
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#2563eb"/>
<circle cx="28" cy="28" r="13" fill="none" stroke="#fff" stroke-width="5"/>
<path d="M38 38l12 12" stroke="#fff" stroke-width="6" stroke-linecap="round"/></svg>"""


@app.route("/icon.svg")
def icon():
    return Response(ICON_SVG, mimetype="image/svg+xml")


@app.route("/manifest.json")
def manifest():
    return jsonify({"name": "경쟁사 광고", "short_name": "경쟁사 광고",
                    "start_url": "/report", "display": "standalone",
                    "background_color": "#f6f7f9", "theme_color": "#2563eb",
                    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"}]})


if __name__ == "__main__":
    print("경쟁사 광고 아카이브 -> http://localhost:%d" % PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)
