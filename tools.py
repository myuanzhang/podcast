import base64
import os

import feedfinder2, feedparser, datetime as dt, time
import requests
from pathlib import Path
from typing import Dict, List, Optional
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from urllib.parse import urljoin, urlparse, urldefrag, urlunparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

from agents import function_tool


from logging_utils import configure_logging, log_error, log_info


configure_logging()

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_PROMPT_CACHE: Dict[str, str] = {}

# Define HTTP headers for feedparser
_FEEDPARSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
}

def search_feeds(site, days=7, max_pages=10, max_feeds=None, verbose=False):
    """Discover and collect feed entries from the given site."""

    log_info(
        "feed.search.start",
        site=site,
        days=days,
        max_pages=max_pages,
        max_feeds=max_feeds,
    )

    PAGINATION_PATTERNS = [
        "{feed}?paged={page}",
        "{feed}/?paged={page}",
    ]

    def _alt_root_patterns(feed_url, page):
        parsed = urlparse(feed_url)
        root = urlunparse((parsed.scheme, parsed.netloc, "/", "", "", ""))
        return [
            f"{root}?feed=rss2&paged={page}",
            f"{root}?feed=atom&paged={page}",
        ]

    def _page_candidates(feed_url, page):
        if page == 1:
            return [feed_url]
        cands = [pat.format(feed=feed_url.rstrip("/"), page=page) for pat in PAGINATION_PATTERNS]
        cands += _alt_root_patterns(feed_url, page)
        return cands

    feeds = feedfinder2.find_feeds(site) or []

    base = site.rstrip("/")
    fallback_candidates = [
        site,
        f"{base}/feed",
        f"{base}/feed/",
        f"{base}/rss",
        f"{base}/rss/",
        f"{base}/atom",
        f"{base}/atom/",
        f"{base}?feed=rss2",
        f"{base}?feed=atom",
    ]

    for candidate in fallback_candidates:
        if candidate and candidate not in feeds:
            feeds.append(candidate)

    seen = set()
    unique_feeds = []
    for feed_url in feeds:
        if feed_url not in seen:
            seen.add(feed_url)
            unique_feeds.append(feed_url)
    feeds = unique_feeds
    if max_feeds:
        feeds = feeds[:max_feeds]

    cutoff = dt.datetime.utcnow() - dt.timedelta(days=days)
    items_by_url = {}

    for feed_url in feeds:
        if verbose:
            log_info("feed.search.feed", site=site, feed_url=feed_url)
        for page in range(1, max_pages + 1):
            hit = None
            variants = [feed_url]
            if feed_url.endswith("/"):
                variants.append(feed_url.rstrip("/"))
            else:
                variants.append(f"{feed_url}/")

            tried = set()
            for base_variant in variants:
                for url in _page_candidates(base_variant, page):
                    if url in tried:
                        continue
                    tried.add(url)
                    d = feedparser.parse(url, request_headers=_FEEDPARSER_HEADERS)
                    if getattr(d, "entries", None):
                        hit = d
                        break
                if hit:
                    break
            if not hit:
                break

            new_entries = 0
            for entry in hit.entries:
                tstruct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
                if not tstruct:
                    continue
                pub = dt.datetime.fromtimestamp(time.mktime(tstruct))
                if pub < cutoff:
                    continue
                url = getattr(entry, "link", None)
                if not url:
                    continue
                item = {
                    "title": getattr(entry, "title", ""),
                    "url": url,
                    "published": pub.isoformat() + "Z",
                    "summary": getattr(entry, "summary", ""),
                    "source_feed": feed_url,
                    "page": page,
                }
                if (url not in items_by_url) or (item["published"] > items_by_url[url]["published"]):
                    items_by_url[url] = item
                    new_entries += 1

            if verbose and new_entries:
                log_info(
                    "feed.search.page",
                    feed_url=feed_url,
                    page=page,
                    new_entries=new_entries,
                )

            if not new_entries:
                break

    items = sorted(items_by_url.values(), key=lambda x: x["published"], reverse=True)
    log_info(
        "feed.search.complete",
        site=site,
        items_found=len(items),
        feeds_checked=len(feeds),
    )
    return items

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_PROMPT_CACHE: Dict[str, str] = {}

def load_prompt(prompt_name: str) -> str:
    if prompt_name in _PROMPT_CACHE:
        return _PROMPT_CACHE[prompt_name]

    prompt_path = PROMPTS_DIR / prompt_name
    try:
        content = prompt_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        log_error("prompt.load_missing", prompt=prompt_name, exc=exc)
        raise
    except OSError as exc:
        log_error("prompt.load_error", prompt=prompt_name, exc=exc)
        raise

    _PROMPT_CACHE[prompt_name] = content
    log_info("prompt.loaded", prompt=prompt_name, length=len(content))
    return content

def extract_content_as_markdown(url: str,
                                *,
                                js_fallback: bool = True,
                                wait_selector: str = "main, article, [role=main], #content, #main-content, .content, .content-area, .article-content",
                                max_iframe_bytes: int = 2_000_000) -> str:
    """
    Fetch URL and convert its main content to Markdown.
    1) Try fast Requests/BS4 path (with retries, iframe inlining, table->markdown).
    2) If result looks empty/boilerplate and js_fallback=True, render with Playwright then re-run the same pipeline.

    Returns: markdown string (never raises; returns "" on unrecoverable errors).
    """
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

    # Optional: only import Playwright when we actually need it
    def _playwright_render(url: str, wait_selector: str, user_agent: str) -> str:
        import asyncio

        # Check if we're already in an async context
        try:
            asyncio.get_running_loop()
            # We're in an async context, need to run in a separate thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(_playwright_render_sync, url, wait_selector, user_agent)
                return future.result()
        except RuntimeError:
            # No event loop running, safe to use sync API directly
            return _playwright_render_sync(url, wait_selector, user_agent)

    def _playwright_render_sync(url: str, wait_selector: str, user_agent: str) -> str:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=user_agent)
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_selector(wait_selector, timeout=20000)
            except Exception:
                pass
            html = page.content()
            browser.close()
            return html

    def _session_with_retries():
        s = requests.Session()
        s.headers.update({
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
        retry = Retry(
            total=3,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=["GET", "HEAD"]
        )
        s.mount("http://", HTTPAdapter(max_retries=retry))
        s.mount("https://", HTTPAdapter(max_retries=retry))
        return s

    def _pick_main_container(soup: BeautifulSoup):
        for sel in wait_selector.split(","):
            sel = sel.strip()
            if not sel:
                continue
            el = soup.select_one(sel)
            if el:
                return el
        return soup.body or soup

    def _absolutize_urls(root_url: str, node: BeautifulSoup):
        for a in node.select("a[href]"):
            href = a.get("href", "")
            absu = urljoin(root_url, href)
            absu, _ = urldefrag(absu)
            a["href"] = absu
        for img in node.select("img[src]"):
            src = img.get("src", "")
            absu = urljoin(root_url, src)
            absu, _ = urldefrag(absu)
            img["src"] = absu

    def _remove_noise(node: BeautifulSoup):
        # Keep iframes for separate inlining step
        for tag in node.select("script, style, noscript, form, nav, header, footer, aside"):
            tag.decompose()

    def _inline_iframes(root_url: str, node: BeautifulSoup, sess: requests.Session):
        iframes = node.select("iframe[src]")
        for fr in iframes:
            src = fr.get("src", "").strip()
            if not src:
                continue
            absu = urljoin(root_url, src)
            try:
                r = sess.get(absu, timeout=15)
                r.raise_for_status()
                if len(r.content) > max_iframe_bytes:
                    fr.decompose()
                    continue
                sub = BeautifulSoup(r.text, "lxml")
                embedded_main = _pick_main_container(sub)
                _remove_noise(embedded_main)
                _absolutize_urls(absu, embedded_main)
                fr.replace_with(embedded_main)
            except Exception:
                fr.decompose()

    def _convert_tables_to_markdown(node: BeautifulSoup):
        tables = node.select("table")
        for tbl in tables:
            try:
                dfs = pd.read_html(str(tbl))
                if not dfs:
                    continue
                df = dfs[0]
                md_table = df.to_markdown(index=False)
                pre = node.new_tag("pre")
                pre["class"] = "md-table"
                pre.string = md_table
                tbl.replace_with(pre)
            except Exception:
                continue

    def _html_to_markdown(html: str, base_url: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        main = _pick_main_container(soup)
        _remove_noise(main)
        _absolutize_urls(base_url, main)
        _convert_tables_to_markdown(main)
        markdown = md(
            str(main),
            heading_style="ATX",
            strip=["span"],
            autolinks=True,
            bullets="*",
        )
        # collapse >2 blank lines
        lines = [ln.rstrip() for ln in markdown.splitlines()]
        cleaned, blank_run = [], 0
        for ln in lines:
            if not ln.strip():
                blank_run += 1
                if blank_run <= 2:
                    cleaned.append("")
            else:
                blank_run = 0
                cleaned.append(ln)
        return "\n".join(cleaned).strip()

    def _is_boilerplate(text: str) -> bool:
        if not text:
            return True

        low = text.lower()

        # Very short -> almost certainly not a useful article/page
        if len(low) < 200:
            return True

        boiler_bits = [
            # JS placeholders
            "you need to enable javascript",
            "this site requires javascript",
            "please enable javascript",
            "loading…",
            "loading...",

            # Consent / cookie walls
            "cookie policy",
            "we value your privacy",
            "before you continue to",
            "manage your privacy settings",
            "consent.yahoo.com",
            "gdpr consent",
            "your privacy controls",
            "vi värdesätter din integritet",   # Swedish variants
            "hantera dina integritetsinställningar",
            "gå till slutet",                  # what you just saw
        ]

        return any(b in low for b in boiler_bits)


    # --- Attempt 1: Requests path (with iframe inlining) ---
    try:
        sess = _session_with_retries()
        resp = sess.get(url, timeout=20)
        resp.raise_for_status()
        if resp.encoding is None:
            resp.encoding = resp.apparent_encoding

        soup = BeautifulSoup(resp.text, "lxml")
        main = _pick_main_container(soup)
        _remove_noise(main)
        _absolutize_urls(resp.url, main)
        _inline_iframes(resp.url, main, sess)
        _convert_tables_to_markdown(main)

        md_fast = md(
            str(main),
            heading_style="ATX",
            strip=["span"],
            autolinks=True,
            bullets="*",
        ).strip()

        # Post-process whitespace
        lines = [ln.rstrip() for ln in md_fast.splitlines()]
        cleaned, blank_run = [], 0
        for ln in lines:
            if not ln.strip():
                blank_run += 1
                if blank_run <= 2:
                    cleaned.append("")
            else:
                blank_run = 0
                cleaned.append(ln)
        md_fast = "\n".join(cleaned).strip()

        if md_fast and not _is_boilerplate(md_fast):
            return md_fast

    except Exception:
        # Fall through to JS path if enabled
        pass

    # --- Attempt 2: Playwright JS fallback ---
    if js_fallback:
        try:
            html = _playwright_render(url, wait_selector, UA)
            md_js = _html_to_markdown(html, url)
            if md_js and not _is_boilerplate(md_js):
                return md_js
        except Exception:
            pass

    # --- Last resort: return empty string ---
    return ""

def script_to_video_genai(veo_json_str: str, filename: str = "update.mp4") -> str:
    """
    Accepts a JSON string (Veo structured prompt), generates an 8s Veo 3 video, saves to filename.
    """
    import json, time
    from google import genai
    from google.genai import types
    from config import GEMINI_API_KEY, GEMINI_VEO_MODEL_NAME

    # Parse JSON → compact text prompt
    veo_json = json.loads(veo_json_str)
    prompt_text = json.dumps(veo_json, ensure_ascii=False)

    client = genai.Client(api_key=GEMINI_API_KEY)

    operation = client.models.generate_videos(
        model=GEMINI_VEO_MODEL_NAME,
        prompt=prompt_text,
        # IMPORTANT: Veo 3 audio is always on; do not pass generateAudio
        config=types.GenerateVideosConfig(
            aspectRatio="16:9",
            # optional: steer style, not required
            # negative_prompt="low quality, text overlays, logos"
        ),
    )

    while not operation.done:
        time.sleep(10)
        operation = client.operations.get(operation)

    video = operation.response.generated_videos[0]  # per docs
    client.files.download(file=video.video)
    video.video.save(filename)
    return f"Video saved to {filename}"


def script_to_voice_dashscope(text: str, filename: str) -> str:
    """
    Converts the provided text to speech using Alibaba Cloud DashScope's TTS API (CosyVoice/Sambert)
    and saves it as an MP3 file.
    """
    from config import DASHSCOPE_TTS_MODEL_NAME, DASHSCOPE_API_KEY
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer
    from pathlib import Path
    
    # Set API key at module level
    dashscope.api_key = DASHSCOPE_API_KEY
    speech_file_path = Path(__file__).parent / filename
    
    # Create speech synthesizer with default model and voice
    synthesizer = SpeechSynthesizer(
        model=DASHSCOPE_TTS_MODEL_NAME,
        voice="longanyang"  # Default voice, can be customized
    )
    
    # Generate audio
    audio = synthesizer.call(text)
    
    # Save audio to file
    with open(speech_file_path, 'wb') as f:
        f.write(audio)
    
    return f"Audio content saved to {speech_file_path}"




def script_to_video_dashscope(veo_json_str: str, filename: str = "update.mp4", size: str = "832*480", duration: int = 8, prompt_extend: bool = True, shot_type: str = "multi") -> str:
    """
    Accepts a JSON string (Veo structured prompt), generates a video using Alibaba Cloud DashScope's Text-to-Video API,
    and saves it to the specified filename.
    """
    import json, time, requests
    from pathlib import Path
    from config import DASHSCOPE_VEO_MODEL_NAME, DASHSCOPE_API_KEY
    
    # Parse JSON → compact text prompt (same as script_to_video_genai)
    veo_json = json.loads(veo_json_str)
    prompt_text = json.dumps(veo_json, ensure_ascii=False)
    
    # API endpoint for task creation
    api_endpoint = "https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis"
    
    # Request headers
    headers = {
        "X-DashScope-Async": "enable",
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json"
    }
    
    # Request body
    request_body = {
        "model": DASHSCOPE_VEO_MODEL_NAME,
        "input": {"prompt": prompt_text},
        "parameters": {
            "size": size,
            "duration": duration,
            "prompt_extend": prompt_extend,
            "shot_type": shot_type
        }
    }
    
    # Create video generation task
    response = requests.post(api_endpoint, headers=headers, json=request_body)
    response_data = response.json()
    
    if "error" in response_data or "output" not in response_data:
        raise Exception(f"Video generation task creation failed: {response_data.get('error', {}).get('message', 'Unknown error')}")
    
    task_id = response_data["output"]["task_id"]
    log_info(f"Video generation task created with ID: {task_id}")
    
    # Poll for task completion
    max_retries = 100
    retry_interval = 15  # seconds
    task_status_url = f"https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
    
    for attempt in range(max_retries):
        time.sleep(retry_interval)
        
        status_response = requests.get(task_status_url, headers=headers)
        status_data = status_response.json()
        
        if "error" in status_data or "output" not in status_data:
            raise Exception(f"Failed to get task status: {status_data.get('error', {}).get('message', 'Unknown error')}")
        
        task_status = status_data["output"]["task_status"]
        log_info(f"Task status check {attempt+1}/{max_retries}: {task_status}")
        
        if task_status == "SUCCEEDED":
            # Debug: print full response structure
            log_info(f"Task succeeded, response structure: {json.dumps(status_data['output'], ensure_ascii=False, indent=2)}")
            
            # Get video URL - depending on API version, it could be in different fields
            if "video_url" in status_data["output"]:
                video_url = status_data["output"]["video_url"]
                break
            elif "results" in status_data["output"] and status_data["output"]["results"]:
                video_url = status_data["output"]["results"][0]["url"]
                break
            else:
                raise Exception(f"Video URL not found in response: {status_data['output']}")
        elif task_status == "FAILED":
            # Get detailed error information from API response
            error_info = status_data['output'].get('task_message', 'Unknown error')
            # Check if there's more detailed error information in the status_data
            if 'error' in status_data:
                error_info = f"{error_info}: {status_data['error'].get('message', '')}"
            raise Exception(f"Video generation failed: {error_info}")
    else:
        raise Exception("Video generation timed out after maximum retries")
    
    # Download the video
    video_response = requests.get(video_url)
    video_file_path = Path(__file__).parent / filename
    
    with open(video_file_path, "wb") as f:
        f.write(video_response.content)
    
    return f"Video saved to {video_file_path}"


def script_to_voice(client, text: str, filename: str) -> str:
    """
    Converts the provided text to speech using OpenAI's TTS API and saves it as an MP3 file.
    """
    from config import OPENAI_TTS_MODEL_NAME
    speech_file_path = Path(__file__).parent / filename

    with client.audio.speech.with_streaming_response.create(
        model=OPENAI_TTS_MODEL_NAME,
        voice="coral",
        input=text,
        instructions=(
            "You will receive a script intended for a podcast or spoken regulatory update. "
            "Please convert it to voice, speaking in a friendly, professional, and conversational tone. "
            "Sound clear and approachable, as if you are guiding listeners through the latest updates."
        ),
    ) as response:
        response.stream_to_file(speech_file_path)

    return f"Audio content saved to {speech_file_path}"

def create_github_pr(
    repo: str,
    branch: str,
    file_name: str,
    file_content: str,
    token: str = None,
    commit_message: str = "Automated PR from agentic workflow",
    base_branch: str = "master",
    pr_title: Optional[str] = None,
):
    """
    Create a file in a new/existing branch and open a Pull Request in GitHub.
    Requires GITHUB_TOKEN environment variable with `repo` scope.
    """
    if not token:
        log_error("github.pr.missing_token", repo=repo, branch=branch)
        return {"success": False, "pr_url": "", "branch": branch, "message": "Missing GITHUB_TOKEN"}

    log_info(
        "github.pr.create.start",
        repo=repo,
        branch=branch,
        file_name=file_name,
        base_branch=base_branch,
    )

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json"
    }

    # 1) Get latest commit SHA of base branch
    r = requests.get(f"https://api.github.com/repos/{repo}/git/refs/heads/{base_branch}", headers=headers)
    if r.status_code != 200:
        log_error(
            "github.pr.base_branch",
            repo=repo,
            branch=branch,
            base_branch=base_branch,
            status_code=r.status_code,
            response=r.text,
        )
        return {"success": False, "pr_url": "", "branch": branch, "message": f"Failed to get base branch: {r.text}"}
    base_sha = r.json()["object"]["sha"]

    # 2) Create branch (ignore if exists)
    requests.post(
        f"https://api.github.com/repos/{repo}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{branch}", "sha": base_sha}
    )

    # 3) Base64 encode file content for GitHub API
    encoded_content = base64.b64encode(file_content.encode("utf-8")).decode("utf-8")

    # 4) Create/Update file in the branch
    url = f"https://api.github.com/repos/{repo}/contents/{file_name}"
    data = {
        "message": commit_message,
        "content": encoded_content,
        "branch": branch
    }
    r = requests.put(url, headers=headers, json=data)
    if r.status_code not in (200, 201):
        log_error(
            "github.pr.commit",
            repo=repo,
            branch=branch,
            file_name=file_name,
            status_code=r.status_code,
            response=r.text,
        )
        return {"success": False, "pr_url": "", "branch": branch, "message": f"Failed to commit file: {r.text}"}

    # 5) Open PR
    pr_url = f"https://api.github.com/repos/{repo}/pulls"
    pr_data = {
        "title": pr_title or f"Automated PR for {file_name}",
        "head": branch,
        "base": base_branch,
        "body": "This PR was created automatically by the regulatory update workflow."
    }
    r = requests.post(pr_url, headers=headers, json=pr_data)
    if r.status_code not in (200, 201):
        log_error(
            "github.pr.create",
            repo=repo,
            branch=branch,
            file_name=file_name,
            status_code=r.status_code,
            response=r.text,
        )
        return {"success": False, "pr_url": "", "branch": branch, "message": f"Failed to create PR: {r.text}"}

    pr_response = r.json()
    log_info(
        "github.pr.create.success",
        repo=repo,
        branch=branch,
        file_name=file_name,
        pr_url=pr_response.get("html_url"),
    )

    return {
        "success": True,
        "pr_url": pr_response.get("html_url", ""),
        "branch": branch,
        "message": "PR created successfully"
    }

if __name__ == "__main__":
    # url = "https://www.yahoo.com/news/articles/chinas-stranded-astronauts-return-space-003557039.html"
    # md = extract_content_as_markdown(url)
    # print(md)
    
    # Test script_to_voice_dashscope
    # text = "Hi, I'm a bot. I can help you with that."
    # speech_file_path = script_to_voice_dashscope(text, "update.mp3")
    # print(speech_file_path)
    
    # Test script_to_video_dashscope
    # Create a valid Veo JSON structure
    test_veo_json = {
        "scene_description": "0-2s: 卡通小猫将军站在悬崖上，身穿金色盔甲；2-4s: 小猫将军骑着战马；4-6s: 老鼠军队向前冲锋；6-8s: 雪山上空乌云密布的战斗场景",
        "visual_style": "可爱与霸气的融合，卡通风格",
        "camera_movement": "0-2s: 特写；2-4s: 中景；4-6s: 全景；6-8s: 远景",
        "main_subject": "卡通小猫将军",
        "background_setting": "悬崖，远处雪山",
        "lighting_mood": "乌云密布，史诗氛围",
        "audio_cue": "0-2s: 背景音乐开始；2-4s: 战马嘶鸣；4-6s: 军队冲锋声；6-8s: 背景音乐高潮",
        "color_palette": ["#FFD700", "#8B0000"],
        "dialog": "青海长云暗雪山，孤城遥望玉门关。黄沙百战穿金甲，不破楼兰终不还",
        "subtitles": "OFF"
    }
    
    import json
    test_veo_json_str = json.dumps(test_veo_json, ensure_ascii=False)
    
    try:
        video_result = script_to_video_dashscope(
            test_veo_json_str, 
            "test_video.mp4",
            size="832*480",
            duration=10,
            prompt_extend=True,
            shot_type="multi"
        )
        print(video_result)
    except Exception as e:
        print(f"Error testing script_to_video_dashscope: {e}")
