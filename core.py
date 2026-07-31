# -*- coding: utf-8 -*-
"""
원고 뽑기 - 핵심 로직
영상 파일 / 영상 링크 -> 한글 음성 텍스트 변환(STT) -> 2~5줄 요약
모두 로컬(오프라인)에서 동작합니다. (Whisper 모델은 최초 1회만 다운로드)
"""
import os
import re
import glob
import math
import tempfile
from collections import Counter

# ---------------------------------------------------------------------------
# ffmpeg 자동 탐색 (yt-dlp 로 링크 다운로드 시 필요)
# ---------------------------------------------------------------------------
def find_ffmpeg():
    """PATH 또는 바탕화면에서 ffmpeg.exe 를 찾아 경로를 반환. 없으면 None."""
    import shutil
    p = shutil.which("ffmpeg")
    if p:
        return p
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    for pattern in ("**/ffmpeg.exe", "**/bin/ffmpeg.exe"):
        hits = glob.glob(os.path.join(desktop, "**", "ffmpeg.exe"), recursive=True)
        if hits:
            return hits[0]
    return None


def ensure_ffmpeg_on_path():
    """찾은 ffmpeg 폴더를 PATH 앞에 추가. ffmpeg 디렉터리 경로 반환(또는 None)."""
    exe = find_ffmpeg()
    if exe:
        d = os.path.dirname(exe)
        if d not in os.environ.get("PATH", ""):
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")
        return d
    return None


# ---------------------------------------------------------------------------
# 링크 -> 오디오 파일 다운로드
# ---------------------------------------------------------------------------
# 쿠키를 시도할 브라우저 순서 (설치된 것만 자동 사용)
_BROWSERS = ["edge", "chrome", "brave", "firefox", "chromium", "opera", "vivaldi"]


def _base_opts(ffdir, outtmpl, progress):
    def hook(d):
        if progress and d.get("status") == "downloading":
            pct = d.get("_percent_str", "").strip()
            progress(f"다운로드 중... {pct}")

    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook],
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}
        ],
    }
    if ffdir:
        opts["ffmpeg_location"] = ffdir
    return opts


def _looks_like_cookies(path):
    """Netscape cookies.txt 형식인지 가볍게 확인."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            head = f.read(4096)
        return ("# Netscape HTTP Cookie File" in head) or ("\t" in head and "youtube" in head.lower())
    except Exception:
        return False


def find_cookies_file(explicit=None, auto_import=True):
    """cookies.txt 를 자동으로 찾는다.

    순서: 인자 > 프로그램 폴더 > (다운로드/바탕화면에서 최신 쿠키파일 자동 수집).
    다운로드 폴더 등에서 찾으면 프로그램 폴더로 복사해 계속 사용한다.
    """
    if explicit and os.path.exists(explicit):
        return explicit

    here = os.path.dirname(os.path.abspath(__file__))
    home = os.path.expanduser("~")

    # 1) 프로그램 폴더에 이미 있으면 그대로 사용
    for name in ("cookies.txt", "youtube_cookies.txt"):
        p = os.path.join(here, name)
        if os.path.exists(p):
            return p

    # 2) 다운로드/바탕화면 등에서 '쿠키처럼 생긴 최신 txt' 자동 탐색
    search_dirs = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "Desktop"),
        home,
    ]
    patterns = ["*cookies*.txt", "*.youtube.com_cookies.txt", "www.youtube.com_cookies.txt"]
    found = []
    for d in search_dirs:
        for pat in patterns:
            for p in glob.glob(os.path.join(d, pat)):
                if os.path.isfile(p) and _looks_like_cookies(p):
                    try:
                        found.append((os.path.getmtime(p), p))
                    except OSError:
                        pass
    if not found:
        return None

    newest = max(found)[1]  # 가장 최근 파일

    # 3) 프로그램 폴더로 복사해 계속 사용 (원본은 그대로 둠)
    if auto_import:
        try:
            import shutil
            dest = os.path.join(here, "cookies.txt")
            shutil.copyfile(newest, dest)
            return dest
        except Exception:
            return newest
    return newest


def download_audio(url, progress=None, cookies_file=None):
    """유튜브 등 링크에서 오디오만 내려받아 mp3 경로 반환.

    다운로드 순서:
      1) cookies.txt 파일(있으면)  ← 가장 확실
      2) 쿠키 없이
      3) 설치된 브라우저 로그인 쿠키 자동 시도
    """
    import yt_dlp

    ffdir = ensure_ffmpeg_on_path()
    tmpdir = tempfile.mkdtemp(prefix="wongo_")
    outtmpl = os.path.join(tmpdir, "audio.%(ext)s")
    cookiefile = find_cookies_file(cookies_file)

    def _try(cookies_browser=None, cookiefile=None):
        opts = _base_opts(ffdir, outtmpl, progress)
        if cookiefile:
            opts["cookiefile"] = cookiefile
        elif cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    def _collect():
        mp3s = glob.glob(os.path.join(tmpdir, "*.mp3"))
        if mp3s:
            return mp3s[0]
        others = [p for p in glob.glob(os.path.join(tmpdir, "*")) if os.path.isfile(p)]
        return others[0] if others else None

    last_err = None

    # 1차: cookies.txt 파일
    if cookiefile:
        try:
            if progress:
                progress("쿠키 파일로 다운로드 중...")
            _try(cookiefile=cookiefile)
            got = _collect()
            if got:
                return got
        except Exception as e:
            last_err = e

    # 2차: 쿠키 없이
    if _collect() is None:
        try:
            _try()
            got = _collect()
            if got:
                return got
        except Exception as e:
            last_err = e

    need_login = last_err is not None and re.search(
        r"Sign in to confirm|not a bot|cookies|login|age", str(last_err), re.I
    )

    # 3차: 브라우저 쿠키 자동 시도
    if last_err is None or need_login:
        for b in _BROWSERS:
            try:
                if progress:
                    progress(f"{b} 로그인 정보로 재시도 중...")
                _try(cookies_browser=b)
                got = _collect()
                if got:
                    return got
            except Exception as e:
                last_err = e
                continue

    # 실패 -> 사용자 친화적 메시지
    msg = str(last_err) if last_err else "알 수 없는 오류"
    if re.search(r"Sign in to confirm|not a bot|cookies|copy .*cookie", msg, re.I):
        raise RuntimeError(
            "유튜브가 로그인 확인(봇 차단)을 요구합니다.\n\n"
            "가장 확실한 해결법 — 쿠키 파일 사용:\n"
            "1) 크롬/엣지에 'Get cookies.txt LOCALLY' 확장프로그램 설치\n"
            "2) 유튜브에 로그인한 상태에서 그 확장으로 cookies.txt 내보내기\n"
            "3) 저장한 cookies.txt 를 이 프로그램 폴더에 넣기 (또는 [쿠키 파일] 버튼으로 지정)\n"
            "4) 다시 [변환 시작]\n\n"
            "간단한 대안: 영상 파일을 직접 내려받아 파일로 넣기(드래그&드롭)."
        )
    if re.search(r"Video unavailable|Private video|removed", msg, re.I):
        raise RuntimeError("영상을 재생할 수 없습니다. (비공개/삭제/지역 제한된 영상일 수 있어요.)")
    raise RuntimeError(f"다운로드 실패: {msg[:300]}")


# ---------------------------------------------------------------------------
# 음성 -> 텍스트 (faster-whisper)
# ---------------------------------------------------------------------------
_MODEL_CACHE = {}


def transcribe(audio_path, model_size="small", progress=None):
    """오디오/영상 파일을 한국어로 받아쓰기. (텍스트, 세그먼트리스트) 반환."""
    from faster_whisper import WhisperModel

    ensure_ffmpeg_on_path()

    if progress:
        progress(f"음성 인식 모델 준비 중... ({model_size})")

    if model_size not in _MODEL_CACHE:
        # CPU + int8 = 가장 가벼운 설정
        _MODEL_CACHE[model_size] = WhisperModel(
            model_size, device="cpu", compute_type="int8"
        )
    model = _MODEL_CACHE[model_size]

    if progress:
        progress("음성 인식 중... (영상 길이에 따라 시간이 걸립니다)")

    segments, info = model.transcribe(
        audio_path,
        language="ko",
        beam_size=5,
        vad_filter=True,  # 무음 구간 제거로 정확도/속도 향상
    )

    parts = []
    total = getattr(info, "duration", 0) or 0
    for seg in segments:
        parts.append(seg.text.strip())
        if progress and total:
            pct = min(100, int(seg.end / total * 100))
            progress(f"음성 인식 중... {pct}%")

    text = " ".join(p for p in parts if p).strip()
    text = re.sub(r"\s+", " ", text)
    return text


# ---------------------------------------------------------------------------
# 오프라인 요약 (빈도 기반 추출 요약, 한국어 지원)
# ---------------------------------------------------------------------------
_STOPWORDS = set(
    """
    그리고 그러나 하지만 그래서 그런데 그러면 또한 또 즉 및 등 이런 저런 그런
    이것 저것 그것 여기 저기 거기 우리 저희 당신 그들 이번 저번 지금 오늘 내일 어제
    입니다 습니다 합니다 됩니다 있습니다 없습니다 것이 것을 것은 수가 수도 때문 통해
    대한 위해 대해 관련 경우 정도 가지 하나 사람 이렇게 저렇게 그렇게 정말 진짜 아주
    너무 매우 조금 많이 다시 계속 바로 먼저 우선 이제 그냥 좀 잘 더 못 안 왜 뭐 네 예
    """.split()
)

_SENT_SPLIT = re.compile(r"(?<=[.!?。])\s+|(?<=[다요죠음함])\.\s*|\n+")


def _split_sentences(text):
    raw = _SENT_SPLIT.split(text)
    sents = []
    for s in raw:
        if not s:
            continue
        s = s.strip()
        if len(s) >= 5:
            sents.append(s)
    return sents


def _tokenize(s):
    # 한글/영문/숫자 단어 추출, 2글자 이상, 불용어 제거
    words = re.findall(r"[가-힣A-Za-z0-9]+", s)
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


def summarize(text, max_lines=4):
    """추출 요약: 핵심 문장 2~max_lines개를 원문 순서대로 반환."""
    sents = _split_sentences(text)
    if len(sents) <= max_lines:
        return "\n".join(f"- {s}" for s in sents)

    # 단어 빈도(문서 전체) 계산
    freq = Counter()
    for s in sents:
        freq.update(_tokenize(s))
    if not freq:
        return "\n".join(f"- {s}" for s in sents[:max_lines])

    maxf = max(freq.values())
    for w in freq:
        freq[w] /= maxf  # 정규화

    # 문장 점수 = 단어 점수 합 / sqrt(길이)  (긴 문장 편향 완화)
    scored = []
    for idx, s in enumerate(sents):
        toks = _tokenize(s)
        if not toks:
            continue
        score = sum(freq[w] for w in toks) / math.sqrt(len(toks))
        # 앞부분 문장 소폭 가중(도입부에 핵심이 많은 경향)
        score *= 1.0 + 0.15 * (1 - idx / len(sents))
        scored.append((score, idx, s))

    n = min(max_lines, max(2, len(sents) // 5 + 2))
    top = sorted(scored, reverse=True)[:n]
    top_sorted = sorted(top, key=lambda x: x[1])  # 원문 순서 복원
    return "\n".join(f"- {s}" for _, _, s in top_sorted)


# ---------------------------------------------------------------------------
# 전체 파이프라인
# ---------------------------------------------------------------------------
def run(source, model_size="small", max_lines=4, progress=None, cookies_file=None):
    """source: 로컬 파일 경로 또는 URL. (transcript, summary) 반환."""
    def log(m):
        if progress:
            progress(m)

    is_url = re.match(r"^https?://", source.strip())
    if is_url:
        audio = download_audio(source.strip(), progress=progress, cookies_file=cookies_file)
    else:
        audio = source.strip().strip('"')
        if not os.path.exists(audio):
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {audio}")

    transcript = transcribe(audio, model_size=model_size, progress=progress)
    if not transcript:
        raise RuntimeError("음성을 인식하지 못했습니다. 오디오에 한국어 음성이 있는지 확인하세요.")

    log("요약 중...")
    summary = summarize(transcript, max_lines=max_lines)
    log("완료")
    return transcript, summary
