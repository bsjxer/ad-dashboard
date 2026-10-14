#!/bin/bash
# 매일 정찰 + 아카이브 + 리포트. cron이 부른다. 겹쳐 돌지 않게 flock.
set -a; . /etc/adarchive/env; set +a
cd /srv/work/ad-dashboard/경쟁사광고아카이브 || exit 1
exec flock -n /run/adarchive-daily.lock /opt/adarchive/venv/bin/python -u scout.py daily
