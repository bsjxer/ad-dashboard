# -*- coding: utf-8 -*-
"""
원고 뽑기 (웹)
브라우저에서 링크로 접속 → 영상 파일 업로드 또는 링크 붙여넣기 → 한글 텍스트 + 요약.

실행:  python web.py     (또는  원고뽑기_웹실행.bat  더블클릭)
접속:  http://localhost:8000
"""
import os
import shutil
import tempfile
import traceback

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

import core

app = FastAPI(title="원고 뽑기")

PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>원고 뽑기 - 영상 음성 → 텍스트</title>
<style>
  :root { --bg:#f4f6fb; --card:#fff; --line:#e3e8f0; --pri:#3457d5; --pri2:#2540a8; --muted:#7a8496; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Malgun Gothic",system-ui,sans-serif; background:var(--bg); color:#1c2333; }
  .wrap { max-width:820px; margin:0 auto; padding:24px 16px 60px; }
  h1 { font-size:22px; margin:8px 0 4px; }
  .sub { color:var(--muted); font-size:14px; margin-bottom:20px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px; margin-bottom:16px; box-shadow:0 1px 3px rgba(20,30,60,.04); }
  .drop { border:2px dashed #b9c6e6; border-radius:12px; padding:34px 16px; text-align:center; color:var(--pri);
          background:#f7f9ff; cursor:pointer; transition:.15s; font-weight:700; }
  .drop.hover { background:#eaf0ff; border-color:var(--pri); }
  .drop small { display:block; color:var(--muted); font-weight:400; margin-top:6px; }
  .row { display:flex; gap:8px; margin-top:14px; flex-wrap:wrap; align-items:center; }
  input[type=text]{ flex:1; min-width:200px; padding:11px 12px; border:1px solid var(--line); border-radius:9px; font-size:14px; }
  select { padding:10px; border:1px solid var(--line); border-radius:9px; font-size:14px; }
  button { background:var(--pri); color:#fff; border:0; padding:11px 18px; border-radius:9px; font-size:15px; font-weight:700; cursor:pointer; }
  button:hover { background:var(--pri2); }
  button:disabled { opacity:.5; cursor:default; }
  label.opt { font-size:14px; color:var(--muted); }
  .status { margin:12px 0; font-size:14px; color:var(--pri); min-height:20px; }
  .bar { height:6px; background:#e6ebf6; border-radius:6px; overflow:hidden; display:none; }
  .bar.on { display:block; }
  .bar i { display:block; height:100%; width:40%; background:var(--pri); animation:slide 1.1s infinite; }
  @keyframes slide { 0%{margin-left:-40%} 100%{margin-left:100%} }
  h3 { font-size:15px; margin:0 0 8px; }
  .box { white-space:pre-wrap; line-height:1.65; font-size:15px; background:#fbfcfe; border:1px solid var(--line);
         border-radius:10px; padding:14px; max-height:340px; overflow:auto; }
  .sumbox { background:#f2f7ff; border-color:#cfe0ff; }
  .tools { display:flex; gap:8px; margin-top:8px; }
  .tools button { background:#eef2fb; color:#2a3550; padding:7px 12px; font-size:13px; }
  .hidden { display:none; }
  .fname { font-size:13px; color:var(--muted); margin-top:8px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🎙️ 원고 뽑기</h1>
  <div class="sub">영상/음성 파일을 올리거나 링크를 붙여넣으면 한글 음성을 텍스트로 바꾸고 2~5줄로 요약해요.</div>

  <div class="card">
    <div id="drop" class="drop">⬆ 여기로 영상 파일을 끌어놓거나 클릭해서 선택
      <small>mp4 · mov · mkv · webm · mp3 · m4a · wav … (1분 내외 권장)</small>
    </div>
    <input id="file" type="file" class="hidden" accept="video/*,audio/*">
    <div id="fname" class="fname"></div>

    <div class="row">
      <input id="url" type="text" placeholder="또는 유튜브 등 영상 링크 붙여넣기 (https://...)">
    </div>
    <div class="row">
      <label class="opt">정확도
        <select id="model">
          <option value="tiny">빠름(tiny)</option>
          <option value="base">보통(base)</option>
          <option value="small" selected>좋음(small)</option>
          <option value="medium">매우좋음(medium)</option>
        </select>
      </label>
      <label class="opt">요약 줄수
        <select id="lines">
          <option>2</option><option>3</option><option selected>4</option><option>5</option>
        </select>
      </label>
      <button id="go">변환 시작</button>
    </div>

    <div id="status" class="status"></div>
    <div id="bar" class="bar"><i></i></div>
  </div>

  <div id="result" class="hidden">
    <div class="card">
      <h3>📌 요약</h3>
      <div id="summary" class="box sumbox"></div>
      <div class="tools"><button onclick="copyBox('summary')">요약 복사</button></div>
    </div>
    <div class="card">
      <h3>📝 전체 원고</h3>
      <div id="transcript" class="box"></div>
      <div class="tools">
        <button onclick="copyBox('transcript')">원고 복사</button>
        <button onclick="download()">.txt 저장</button>
      </div>
    </div>
  </div>
</div>

<script>
const $ = id => document.getElementById(id);
let chosenFile = null;

const drop = $('drop'), fileInput = $('file');
drop.onclick = () => fileInput.click();
fileInput.onchange = e => { if (e.target.files[0]) setFile(e.target.files[0]); };
['dragover','dragenter'].forEach(ev => drop.addEventListener(ev, e=>{e.preventDefault();drop.classList.add('hover');}));
['dragleave','drop'].forEach(ev => drop.addEventListener(ev, e=>{e.preventDefault();drop.classList.remove('hover');}));
drop.addEventListener('drop', e => { if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]); });
function setFile(f){ chosenFile = f; $('fname').textContent = '선택된 파일: ' + f.name; $('url').value=''; }
$('url').addEventListener('input', ()=>{ if($('url').value.trim()){ chosenFile=null; $('fname').textContent=''; fileInput.value=''; }});

$('go').onclick = async () => {
  const url = $('url').value.trim();
  if (!chosenFile && !url) { alert('영상 파일을 올리거나 링크를 붙여넣어 주세요.'); return; }

  $('go').disabled = true;
  $('bar').classList.add('on');
  $('result').classList.add('hidden');
  $('status').textContent = chosenFile ? '업로드 후 변환 중... (영상 길이에 따라 시간이 걸려요)' : '링크에서 가져와 변환 중...';

  const fd = new FormData();
  if (chosenFile) fd.append('file', chosenFile);
  if (url) fd.append('url', url);
  fd.append('model', $('model').value);
  fd.append('lines', $('lines').value);

  try {
    const res = await fetch('/transcribe', { method:'POST', body: fd });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || ('오류 ' + res.status));
    $('summary').textContent = data.summary;
    $('transcript').textContent = data.transcript;
    $('result').classList.remove('hidden');
    $('status').textContent = '완료 ✅';
  } catch (err) {
    $('status').textContent = '❌ ' + err.message;
    alert(err.message);
  } finally {
    $('go').disabled = false;
    $('bar').classList.remove('on');
  }
};

function copyBox(id){ navigator.clipboard.writeText($(id).textContent); $('status').textContent='복사했어요.'; }
function download(){
  const t = '[요약]\\n'+$('summary').textContent+'\\n\\n[전체 원고]\\n'+$('transcript').textContent+'\\n';
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([t], {type:'text/plain;charset=utf-8'}));
  a.download = '원고.txt'; a.click();
}
</script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(None),
    url: str = Form(None),
    model: str = Form("small"),
    lines: int = Form(4),
):
    tmpdir = None
    try:
        if file is not None and file.filename:
            # 업로드 파일을 임시 저장
            tmpdir = tempfile.mkdtemp(prefix="wongo_web_")
            path = os.path.join(tmpdir, file.filename)
            with open(path, "wb") as f:
                shutil.copyfileobj(file.file, f)
            source = path
        elif url:
            source = url.strip()
        else:
            return JSONResponse({"error": "파일 또는 링크가 필요합니다."}, status_code=400)

        transcript, summary = core.run(source, model_size=model, max_lines=int(lines))
        return {"transcript": transcript, "summary": summary}

    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        if tmpdir and os.path.isdir(tmpdir):
            shutil.rmtree(tmpdir, ignore_errors=True)


PORT = int(os.environ.get("WONGO_PORT", "8010"))


def main():
    core.ensure_ffmpeg_on_path()
    print(f"\n  원고 뽑기 웹 실행 중 →  http://localhost:{PORT}\n")
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
