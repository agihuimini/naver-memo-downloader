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
from urllib.parse import parse_qs, urlencode

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("pip3 install playwright && python3 -m playwright install chromium")
    sys.exit(1)

OUTPUT_DIR = Path("naver_memos")
SIZE_PER_PAGE = 100
UNCATEGORIZED = "미분류"


def ask_filter_mode() -> str:
    """
    저장 방식 선택.
    반환값: 'bulk' | 'split'
    """
    print("=" * 44)
    print("  저장 방식을 선택하세요")
    print("=" * 44)
    print("  1) 일괄  — 폴더별로만 분류해서 저장")
    print("  2) 구별  — 폴더 안을 '중요 / 일반'으로 나눠서 저장")
    print()

    while True:
        choice = input("선택 (1/2): ").strip()
        if choice == "1":
            print("→ '일괄' 모드로 실행합니다.\n")
            return "bulk"
        if choice == "2":
            print("→ '구별' 모드로 실행합니다.\n")
            return "split"
        print("1 또는 2를 입력해 주세요.")


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|\n\r\t]', '_', name).strip()
    name = re.sub(r'_+', '_', name).strip('_')
    return name[:60] if name else "untitled"


def format_datetime(ms) -> str:
    """밀리초 타임스탬프 → 'YYYY-MM-DD HH:MM:SS'"""
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
    """메모 dict → (파일명, 마크다운 내용)"""
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
    filter_mode = ask_filter_mode()  # 'all' | 'important' | 'normal'

    OUTPUT_DIR.mkdir(exist_ok=True)
    print(f"저장 폴더: {OUTPUT_DIR.resolve()}\n")

    first_request: dict = {}
    first_response: dict = {}
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

        # ── 2단계: API 인터셉트 + 페이지 로드 ──────────────────────
        print("[2단계] 메모 서비스 로드 중...")

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
                    all_memos.extend(memos)
                    print(f"  첫 배치: {len(memos)}개 (전체 {data.get('totalCount')}개)")
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        await page.goto("https://memo.naver.com/")
        await page.wait_for_load_state("networkidle")
        await asyncio.sleep(3)

        # ── 3단계: 폴더 목록 조회 ───────────────────────────────────
        print("\n[3단계] 폴더 목록 조회 중...")
        folder_result = await page.evaluate("""
            async () => {
                try {
                    const r = await fetch('/folder/folderList', {credentials: 'include'});
                    return await r.json();
                } catch(e) { return null; }
            }
        """)

        # folderId → 폴더명 매핑
        folder_map: dict[int, str] = {}
        if folder_result and folder_result.get('code') == 'SUCCESS':
            folders = (folder_result.get('data') or {}).get('folderList') or []
            for f in folders:
                fid = f.get('folderId')
                fname = f.get('folderName') or f.get('name') or str(fid)
                if fid is not None:
                    folder_map[fid] = fname
            print(f"  폴더 {len(folder_map)}개: {list(folder_map.values())}")
        else:
            print("  폴더 목록을 가져오지 못했습니다. 단일 폴더로 저장합니다.")

        # ── 4단계: 나머지 메모 cursor 페이지네이션 ──────────────────
        total = first_response.get('total', 0)
        cursor = first_response.get('cursor', '')

        if total > len(all_memos) and first_request:
            print(f"\n[4단계] 나머지 {total - len(all_memos)}개 다운로드...")

            orig_headers = first_request.get('headers', {})
            safe_headers = {
                k: v for k, v in orig_headers.items()
                if k.lower() not in ('host', 'content-length', ':method', ':path', ':scheme', ':authority')
            }
            safe_headers['content-type'] = 'application/x-www-form-urlencoded'
            headers_js = json.dumps(safe_headers)

            orig_params = {k: v[0] for k, v in parse_qs(
                first_request.get('body', ''), keep_blank_values=True
            ).items()}
            orig_params['sizePerPage'] = str(SIZE_PER_PAGE)
            orig_params['excludeHtml'] = 'false'

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
                    print(f"\n  오류: {json.dumps(result)[:200]}")
                    break

                data = result.get('data') or {}
                memos = data.get('memoList') or []
                next_cursor = data.get('nextCursor') or ''

                if not memos:
                    break

                all_memos.extend(memos)
                print(f"  {len(all_memos)}/{total}개...", end='\r', flush=True)

                if not next_cursor or next_cursor == cursor:
                    break

                cursor = next_cursor
                await asyncio.sleep(0.1)

            print()

        await browser.close()

    # ── 5단계: 폴더별로 분류해서 저장 ──────────────────────────────
    seen: set = set()
    unique: list[dict] = []
    for m in all_memos:
        mid = str(m.get('memoSeq') or id(m))
        if mid not in seen:
            seen.add(mid)
            unique.append(m)

    mode_label = "일괄" if filter_mode == "bulk" else "구별"
    print(f"\n[5단계] 마크다운 저장 중... ({mode_label} / 총 {len(unique)}개)")

    if not unique:
        print("저장할 메모가 없습니다.")
        return

    filename_counter: dict[str, int] = {}
    dir_counts: dict[str, int] = {}
    saved = 0

    for memo in unique:
        folder_id = memo.get('folderId')
        folder_name = folder_map.get(folder_id, UNCATEGORIZED) if folder_map else UNCATEGORIZED

        if filter_mode == "split":
            sub = "중요" if memo.get('important') else "일반"
            save_dir = OUTPUT_DIR / sanitize_filename(folder_name) / sub
        else:
            save_dir = OUTPUT_DIR / sanitize_filename(folder_name)

        save_dir.mkdir(parents=True, exist_ok=True)

        filename, content = memo_to_markdown(memo)

        key = str(save_dir / filename)
        if key in filename_counter:
            # 중복 시 생성일시를 접미사로 붙여 구분
            created = format_datetime(memo.get('createdTime'))
            dt_suffix = created.replace('-', '').replace(':', '').replace(' ', '_') if created else ''
            filename = f"{filename}_{dt_suffix}" if dt_suffix else f"{filename}_{memo.get('memoSeq', id(memo))}"
            # 생성일시도 같은 극단적 중복은 memoSeq로 보장
            key2 = str(save_dir / filename)
            if key2 in filename_counter:
                filename = f"{filename}_{memo.get('memoSeq', id(memo))}"
        filename_counter[str(save_dir / filename)] = True

        (save_dir / f"{filename}.md").write_text(content, encoding="utf-8")
        dir_key = str(save_dir.relative_to(OUTPUT_DIR))
        dir_counts[dir_key] = dir_counts.get(dir_key, 0) + 1
        saved += 1

    print()
    print("저장 결과:")
    for path, cnt in sorted(dir_counts.items()):
        print(f"  {path}/ → {cnt}개")
    print(f"\n완료! 총 {saved}개 메모를 '{OUTPUT_DIR}/' 폴더에 저장했습니다.")
    print(f"경로: {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
