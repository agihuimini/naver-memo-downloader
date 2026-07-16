# 네이버 메모 다운로더

[memo.naver.com](https://memo.naver.com)의 메모 전체를 Markdown(`.md`) 파일로 저장하는 Python 스크립트입니다.

## 기능

- 네이버 메모 **전체 일괄 다운로드** (수천 개도 가능)
- **폴더(카테고리)별 하위 디렉토리**로 자동 분류
- 메모 내용을 **Markdown 형식**으로 변환 (볼드, 이탤릭, 링크, 목록 등)
- **생성 일시**를 `YYYY-MM-DD HH:MM:SS` 형식으로 기록
- 메모 첫 줄을 **제목(H1)**으로 자동 표기
- 파일명 중복 시 자동으로 `_2`, `_3` 접미사 처리
- cursor 기반 페이지네이션으로 API를 안정적으로 순회

## 출력 형식

```markdown
# 메모 첫 줄이 제목이 됩니다

> 생성: 2024-05-01 14:32:07
> 수정: 2024-05-03 09:15:44

메모 본문 내용...
- 목록 항목
- 또 다른 항목
```

## 요구 사항

- Python 3.8 이상
- [Playwright](https://playwright.dev/python/) (브라우저 자동화)

## 설치

```bash
pip install playwright
python -m playwright install chromium
```

## 사용법

```bash
python naver_memo_downloader.py
```

1. 실행하면 Chromium 브라우저가 자동으로 열립니다.
2. **네이버에 로그인**합니다 (2단계 인증 포함).
3. 로그인 완료 후 스크립트가 자동으로 진행됩니다.
4. 완료 후 현재 디렉토리의 `naver_memos/` 폴더에 `.md` 파일이 저장됩니다.

```
naver_memos/
├── 내 메모/
│   ├── 오늘 할 일.md
│   └── 레시피 메모.md
├── 업무/
│   └── 회의록 2024-05-01.md
├── 개인/
│   └── 여행 계획.md
└── 미분류/       ← 폴더가 없는 메모
    └── ...
```

## 동작 원리

1. Playwright로 Chromium을 실행해 네이버 로그인
2. `memo.naver.com` 접속 후 페이지가 보내는 API 요청(`POST /api/memo/select/list`) 헤더와 cursor를 캡처
3. 동일 헤더로 `nextCursor` 기반 페이지네이션을 반복하여 전체 메모 수집
4. HTML 내용을 Markdown으로 변환 후 `.md` 파일로 저장

## 주의 사항

- 이 스크립트는 **본인 계정의 메모**만 다운로드합니다.
- 네이버 로그인 정보는 스크립트에 저장되지 않으며, 브라우저 세션만 사용합니다.
- 네이버 메모 API 구조 변경 시 동작하지 않을 수 있습니다.

## 라이선스

MIT
