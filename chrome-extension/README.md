# namuai - Gemini 이미지 자동 생성 확장 프로그램

namuai 웹 UI(`/image-prompts`)에서 zip 업로드로 생성한 이미지 프롬프트를 불러와
Gemini(gemini.google.com)에서 자동으로 이미지를 생성하고, 생성된 이미지를
자동으로 다운로드하는 크롬 확장 프로그램입니다.

## 설치 (개발자 모드 · 압축해제 로드)

1. 크롬 주소창에 `chrome://extensions` 입력 후 이동
2. 우측 상단 "개발자 모드" 켜기
3. "압축해제된 확장 프로그램을 로드합니다" 클릭
4. 이 저장소의 `chrome-extension` 폴더 선택

## 사용 순서

1. `python shorts_app.py` 로 로컬 서버 실행 (기본 `http://localhost:5000`)
2. 브라우저에서 `http://localhost:5000/image-prompts` 접속 → zip 업로드 → "프롬프트 생성"
3. 화면에 표시된 **서버 주소**와 **Job ID**를 확인
4. 확장 프로그램 아이콘 클릭 → 팝업에 서버 주소 / Job ID 입력 → "불러오기"
5. "자동 생성 시작" 클릭
   - Gemini 탭이 없으면 자동으로 새 탭이 열립니다 (로그인이 필요하면 먼저 로그인하세요)
   - 프롬프트를 순서대로 입력 → 전송 → 이미지 생성 대기 → 새로 생성된 이미지 자동 다운로드를 반복합니다
6. 다운로드된 이미지는 `다운로드 폴더/namuai-gemini/<Job ID>/` 안에 저장됩니다
7. 웹 UI(`/image-prompts`)의 진행 상태가 실시간으로 갱신됩니다 (대기 / 생성 중 / 완료 / 실패)
8. 언제든 팝업의 "중지" 버튼으로 자동 생성을 멈출 수 있습니다

## zip 파일 구성

- `prompts.json` / `prompts.csv` / `prompts.txt` 매니페스트를 포함하면 해당 내용을 우선 사용합니다
  - json: `[{"name": "...", "description": "...", "style": "photo"}, ...]`
  - csv: `name,description,style` 컬럼
  - txt: 한 줄에 하나씩 프롬프트 설명
- 매니페스트가 없으면 zip 안의 이미지 파일들을 스캔합니다
  - `product_red_shoes.jpg` + `product_red_shoes.txt`(같은 이름의 설명 파일)가 있으면 설명을 사용
  - 없으면 파일명을 정리해 프롬프트 기초로 사용

## 알려진 제한 사항

- Gemini 웹 UI의 DOM 구조는 구글이 예고 없이 변경할 수 있습니다. 자동화가 동작하지 않으면
  `content.js` 상단의 `SELECTORS.input` / `SELECTORS.sendButton` 값을 실제 페이지 구조에 맞게
  브라우저 개발자 도구로 확인 후 수정하세요.
- 이미지 생성 대기는 최대 120초까지 기다리며, 그 이후에는 실패로 표시하고 다음 프롬프트로 넘어갑니다.
- Manifest V3 서비스 워커는 일정 시간 유휴 상태이면 종료될 수 있습니다. 이미지 생성을 기다리는
  로직은 content script(활성 탭)에서 실행되며, 주기적인 heartbeat 메시지로 백그라운드를 깨워
  진행 상황을 계속 반영합니다.
- 과도하게 빠른 연속 요청은 Gemini의 사용 정책/속도 제한에 위배될 수 있으므로, 프롬프트 사이에
  3~6초의 무작위 대기 시간을 두었습니다. 대량 생성 시 계정 사용 정책을 꼭 확인하세요.
