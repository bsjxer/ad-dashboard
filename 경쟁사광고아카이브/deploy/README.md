# 서버 배포 (경쟁사 광고 아카이브)

| 무엇 | 어디 |
|---|---|
| 코드 | `/srv/work/ad-dashboard/경쟁사광고아카이브` (작업 사본에서 바로 돈다) |
| 수집물(DB·소재·리포트) | `/srv/data/adarchive` — 저장소 밖 |
| 파이썬 | `/opt/adarchive/venv` (playwright·flask·httpx·gunicorn) |
| 대시보드 | `https://64.176.226.7:8444/report` — 비밀번호 없음(ufw가 사무실 IP만 허용). 걸려면 `/etc/adarchive/env`에 DASHBOARD_PASSWORD |
| 매일 실행 | `/etc/cron.d/adarchive` 07:30 KST → 로그 `/var/log/adarchive-daily.log` |

설치(최초 1회, 이미 해둠):

```bash
python3 -m venv /opt/adarchive/venv
/opt/adarchive/venv/bin/pip install playwright flask httpx gunicorn
/opt/adarchive/venv/bin/python -m playwright install --with-deps chromium
cp adarchive-web.service /etc/systemd/system/ && systemctl enable --now adarchive-web
cp nginx-adarchive.conf /etc/nginx/sites-enabled/adarchive && nginx -t && systemctl reload nginx
cp cron-adarchive /etc/cron.d/adarchive
ufw allow from 112.217.194.106 to any port 8444 proto tcp
```

`/etc/adarchive/env` (600):

```
ADARCHIVE_DATA=/srv/data/adarchive
# DASHBOARD_PASSWORD=...   (지금은 꺼둠)
```

수동 실행: `deploy/adarchive-daily.sh` · 리포트만 보기: `scout.py print`
