#!/usr/bin/env python3
"""
네이버 메모(memo.naver.com) → Markdown 다운로더

설치:
  pip3 install playwright
  playwright install chromium

실행:
  python3 naver_memo_downloader.py
"""

import asyncio
import json
import re
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("pip3 install playwright && python3 -m playwright install chromium")
    sys.exit(1)

OUTPUT_DIR = Path("naver_memos")
SIZE_PER_PAGE = 100


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|\n\r\t]', '_', name).strip()
    name = re.sub(r'_+', '_', name).strip('_')
    return name[:60] if name else "untitled"


def format_datetime(ms) -> str:
    if not ms:
        return ''
    from datetime import datetime, timezone
    try:
        ts = int(ms)
        if ts > 9_999_999_999:
            ts //= 1000
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception:
        return str(ms)


def html_to_md(html: str) -> str:
    if not html:
        return ""
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</p>', '\n\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<p[^>]*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<li[^>]*>', '- ', html, flags=re.IGNORECASE)
    html = re.sub(r'</li>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</?[ou]l[^>]*>', '\n', html, flags=re.IGNORECASE)
    for level, tag in enumerate(['h1', 'h2', 'h3', 'h4'], 1):
        html = re.sub(rf'<{tag}[^>]*>(.*?)</{tag}>', '#' * level + r' \1\n',
                      html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<(strong|b)[^>]*>(.*?)</\1>', r'**\2**', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<a[^>]*href=["\']([^"\']*)["\'][^>]*>(.*?)</a>', r'[\2](\1)',
                  html, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r'<[^>]+>', '', html)
    for ent, ch in {'&amp;': '&', '&lt;': '<', '&gt;': '>', '&nbsp;': ' ',
                    '&quot;': '"', '&#39;': "'", '&#x27;': "'"}.items():
        html = html.replace(ent, ch)
    html = re.sub(r'\n{3,}', '\n\n', html)
    return html.strip()


def memo_to_markdown(memo: dict) -> tuple[str, str]:
    plain = memo.get('memoPlainContent') or ''
    first_line = plain.strip().split('\n')[0].strip() if plain.strip() else ''
    content_html = memo.get('content') or ''
    created = format_datetime(memo.get('createdTime'))
    modified = format_datetime(memo.get('lastModifiedTime'))
    memo_id = str(memo.get('memoSeq') or '')

    content_md = html_to_md(content_html) if content_html else plain.strip()

    lines = []
    if first_line:
        lines.append(f"# {first_line}")
        lines.append("")
    if created:
        lines.append(f"> 생성: {created}")
    if modified and modified != created:
        lines.append(f"> 수정: {modified}")
    if created or modified:
        lines.append("")
    lines.append(content_md)

    if first_line:
        filename = sanitize_filename(first_line)
    else:
        created_compact = created.replace('-', '').replace(':', '').replace(' ', '_') if created else ''
        filename = f"{created_compact}_{memo_id}" if created_compact else f"memo_{memo_id}"

    return filename, '\n'.join(lines)


async def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"저장 폴더: {OUTPUT_DIR.resolve()}\n")

    # 페이지가 보낸 실제 요청 헤더 + 첫 응답 데이터 캡처
    first_request: dict = {}   # {headers, body}
    first_response: dict = {}  # {total, cursor, memos}
    all_memos: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        # ── 1단계: 로그인 ───────────────────────────────────────────
        print("[1단계] 네이버 로그인")
        print("브라우저가 열리면 로그인해 주세요.\n")
        await page.goto("https://nid.naver.com/nidlogin.login?mode=form")
        try:
            await page.wait_for_function(
                "() => !location.href.includes('nidlogin')", timeout=180_000
            )
        except Exception:
            print("로그인 대기 시간 초과.")
            await browser.close()
            return
        print("로그인 완료!\n")

        # ── 2단계: 요청/응답 인터셉트 ──────────────────────────────
        print("[2단계] 메모 서비스 로드 및 첫 API 호출 캡처 중...")

        async def on_request(request):
            if "select/list" in request.url and not first_request:
                try:
                    first_request['headers'] = dict(request.headers)
                    first_request['body'] = request.post_data or ""
                    first_request['method'] = request.method
                except Exception:
                    pass

        async def on_response(response):
            if "select/list" not in response.url or response.status != 200:
                return
            try:
                ct = response.headers.get("content-type", "")
                if "json" not in ct:
                    return
                body = await response.json()
                if body.get('code') != 'SUCCESS':
                    return
                data = body.get('data') or {}
                memos = data.get('memoList') or []
                if memos and not first_response:
                    first_response['total'] = data.get('totalCount') or 0
                    first_response['cursor'] = data.get('nextCursor') or ''
                    first_response['data_keys'] = list(data.keys())
                    all_memos.extend(memos)
                    print(f"  첫 배치 캡처: {len(memos)}개 (전체 {data.get('totalCount')}개)")
                    print(f"  data 키: {list(data.keys())}")
                    print(f"  nextCursor: '{data.get('nextCursor')}'")
            except Exception as e:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        await page.goto("https://memo.naver.com/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)

        total = first_response.get('total', 0)
        cursor = first_response.get('cursor', '')
        print(f"\n  캡처된 요청 헤더: {list(first_request.get('headers', {}).keys())}")
        print(f"  원본 body: {first_request.get('body', '')[:200]}")

        # ── 3단계: cursor로 나머지 메모 가져오기 ───────────────────
        if total > len(all_memos) and first_request:
            print(f"\n[3단계] 나머지 {total - len(all_memos)}개 다운로드...")

            # 원본 헤더를 JS에서 사용할 수 있게 변환
            orig_headers = first_request.get('headers', {})
            # fetch에 포함할 헤더 (민감한 헤더 제외, content-type 포함)
            safe_headers = {
                k: v for k, v in orig_headers.items()
                if k.lower() not in ('host', 'content-length', ':method', ':path', ':scheme', ':authority')
            }
            safe_headers['content-type'] = 'application/x-www-form-urlencoded'

            headers_js = json.dumps(safe_headers)

            # 원본 body에서 파라미터 파싱 후 cursor/sizePerPage만 교체
            from urllib.parse import parse_qs, urlencode
            orig_body = first_request.get('body', '')
            orig_params = {k: v[0] for k, v in parse_qs(orig_body, keep_blank_values=True).items()}
            orig_params['sizePerPage'] = str(SIZE_PER_PAGE)
            orig_params['excludeHtml'] = 'false'  # HTML 포함으로 변경

            while len(all_memos) < total:
                orig_params['cursor'] = cursor
                body_str = urlencode(orig_params)

                result = await page.evaluate(f"""
                    async () => {{
                        try {{
                            const r = await fetch('/api/memo/select/list', {{
                                method: 'POST',
                                credentials: 'include',
                                headers: {headers_js},
                                body: {json.dumps(body_str)}
                            }});
                            return await r.json();
                        }} catch(e) {{ return {{'error': String(e)}}; }}
                    }}
                """)

                if not result or result.get('error') or result.get('code') != 'SUCCESS':
                    print(f"\n  오류: {json.dumps(result)[:300]}")
                    break

                data = result.get('data') or {}
                memos = data.get('memoList') or []
                next_cursor = data.get('nextCursor') or ''

                if not memos:
                    print(f"\n  빈 응답. data 키: {list(data.keys())}")
                    break

                all_memos.extend(memos)
                print(f"  {len(all_memos)}/{total}개...", end='\r', flush=True)

                if not next_cursor or next_cursor == cursor:
                    print(f"\n  cursor 소진 (마지막 cursor='{next_cursor}')")
                    break

                cursor = next_cursor
                await asyncio.sleep(0.1)

            print()

        await browser.close()

    # ── 4단계: 중복 제거 후 저장 ────────────────────────────────────
    seen: set = set()
    unique: list[dict] = []
    for m in all_memos:
        mid = str(m.get('memoSeq') or id(m))
        if mid not in seen:
            seen.add(mid)
            unique.append(m)

    print(f"\n[4단계] 마크다운 저장 중... (총 {len(unique)}개)")

    if not unique:
        print("저장할 메모가 없습니다.")
        return

    filename_counter: dict[str, int] = {}
    saved = 0

    for memo in unique:
        filename, content = memo_to_markdown(memo)
        base = filename
        cnt = filename_counter.get(base, 0) + 1
        filename_counter[base] = cnt
        if cnt > 1:
            filename = f"{base}_{cnt}"

        filepath = OUTPUT_DIR / f"{filename}.md"
        filepath.write_text(content, encoding="utf-8")
        saved += 1

    print(f"\n완료! {saved}개 메모를 '{OUTPUT_DIR}/' 폴더에 저장했습니다.")
    print(f"경로: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
