# -*- coding: utf-8 -*-
"""중복 소재 파일 정리.

fbcdn URL 은 접근할 때마다 서명 쿼리스트링이 바뀌기 때문에, 예전 버전에서는
같은 광고의 같은 소재를 재수집할 때마다 새 파일로 또 받았다.
쿼리스트링을 뗀 경로(url_key)가 같으면 같은 소재이므로 하나만 남긴다.

  python cleanup_media.py          # 얼마나 줄어드는지 보기만 (삭제 안 함)
  python cleanup_media.py --yes    # 실제로 삭제
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

import db


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f%s" % (n, unit)
        n /= 1024.0
    return "%.1fTB" % n


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="실제로 삭제")
    a = ap.parse_args()

    con = db.connect()
    rows = con.execute(
        "SELECT id, ad_archive_id, url_key, local_path FROM media ORDER BY id"
    ).fetchall()

    groups = defaultdict(list)
    for r in rows:
        groups[(r["ad_archive_id"], r["url_key"])].append(r)

    # 지울 대상: 그룹마다 파일이 있는 행 하나만 남기고 나머지
    doomed = []
    for _, items in groups.items():
        if len(items) < 2:
            continue
        with_file = [r for r in items
                     if r["local_path"] not in (None, "", "FAILED")]
        keep = with_file[0] if with_file else items[0]
        doomed += [r for r in items if r["id"] != keep["id"]]

    freed = 0
    missing = 0
    for r in doomed:
        if r["local_path"] in (None, "", "FAILED"):
            continue
        f = db.MEDIA_DIR / r["local_path"]
        if f.exists():
            freed += f.stat().st_size
        else:
            missing += 1

    # DB 에 없는데 디스크에만 남은 파일
    known = set()
    for r in rows:
        if r["local_path"] not in (None, "", "FAILED"):
            known.add((db.MEDIA_DIR / r["local_path"]).resolve())
    orphans, orphan_size = [], 0
    for f in db.MEDIA_DIR.rglob("*"):
        if f.is_file() and f.resolve() not in known:
            orphans.append(f)
            orphan_size += f.stat().st_size

    print("중복 행: %d개 (확보 가능 %s)" % (len(doomed), human(freed)))
    print("고아 파일: %d개 (%s)" % (len(orphans), human(orphan_size)))
    if missing:
        print("파일이 이미 없는 행: %d개" % missing)

    if not a.yes:
        print("\n삭제하지 않았습니다. 실제로 지우려면 --yes 를 붙이세요.")
        con.close()
        return

    gone = 0
    for r in doomed:
        if r["local_path"] not in (None, "", "FAILED"):
            f = db.MEDIA_DIR / r["local_path"]
            try:
                if f.exists():
                    f.unlink()
                    gone += 1
            except Exception as e:
                print("  삭제 실패 %s: %s" % (f.name, type(e).__name__))
        con.execute("DELETE FROM media WHERE id=?", (r["id"],))
    for f in orphans:
        try:
            f.unlink()
            gone += 1
        except Exception:
            pass
    con.commit()
    con.close()
    print("\n파일 %d개 삭제, DB 행 %d개 정리 (%s 확보)"
          % (gone, len(doomed), human(freed + orphan_size)))


if __name__ == "__main__":
    main()
