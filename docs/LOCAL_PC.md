# 내 PC에서 실제 MODAM 채팅 실행

Docker Desktop(Windows/macOS) 또는 Docker Engine + Compose v2(Linux), Git, Python 3.10 이상이 필요하다. Node/uv/PostgreSQL은 컨테이너에 설치되므로 PC에 따로 설치하지 않아도 된다. Docker를 먼저 실행한다.

## 처음 실행

같은 부모 폴더에서 저장소를 준비한다. 채팅 실행에는 modam-chat과 modam-agi가 필요하며 RAG/ONTOLOGY는 독립 프로젝트다.

```bash
git clone https://github.com/woohopark/MODAM-CHAT.git modam-chat
git clone https://github.com/woohopark/MODAM-AGI.git modam-agi
cd modam-agi
python scripts/local-chat.py setup
python scripts/local-chat.py start
python scripts/local-chat.py account
```

macOS/Linux에서 python 명령이 없으면 python3, Windows에서는 py -3로 실행한다. 이미 저장소가 있으면 각 저장소에서 git pull --ff-only로 갱신하고 clone은 생략한다.

setup은 Groq 키를 화면에 표시하지 않고 입력받아 Git 제외 .local/groq.env에 저장한다. 랜덤 DB 비밀번호와 로컬 설정은 .local/compose.env에 생성한다. 기존 설정/키/DB 비밀번호는 덮어쓰지 않는다. 이 채팅의 클라우드에 등록했던 키 파일과 계정은 PC에 자동 복사되지 않으므로 PC에서 키를 입력하고 계정을 생성한다.

start는 이미지 빌드, PostgreSQL, migration, AGI API, 별도 worker, 프론트/BFF를 시작하고 health 확인을 기다린다. 첫 빌드에는 이미지와 패키지 다운로드 시간이 필요하다. account에서 로그인 비밀번호(12자 이상)를 두 번 입력한다. 기본 아이디는 modam-admin이며 다른 아이디는 --username 옵션으로 지정한다. 중복 계정은 다시 생성하지 않는다.

브라우저에서 **http://localhost:3300**을 연다. 생성한 계정으로 로그인하고 Cloud 전송 동의를 선택한다. 일반 대화 모드에서 실제 Groq 답변과 멀티턴을 사용할 수 있다. 대화/계정은 로컬 PostgreSQL volume에 유지되고 다크 모드를 지원한다. 기업 조회용 RAG/ONTOLOGY MCP는 아직 연결되지 않았다. Groq 호출에는 인터넷 연결이 필요하다.

## 중지·재개·상태

```bash
python scripts/local-chat.py status
python scripts/local-chat.py stop
python scripts/local-chat.py start
```

stop은 컨테이너만 중지하고 데이터를 지우지 않는다. 다음 start에서 같은 계정과 대화를 유지한다. Docker의 volume 삭제 명령은 일반 중지 절차에 포함하지 않는다.

## 실패 확인

Docker Desktop을 실행했는지, modam-chat과 modam-agi가 형제 폴더인지, 3300 포트가 비어 있는지 확인한다. 로그는 다음 명령으로 확인한다. 로그를 공유할 때 환경변수 파일이나 키/비밀번호를 함께 올리지 않는다.

```bash
docker compose --env-file .local/compose.env -f deployment/compose.local.yaml logs --tail 50 agi worker chat
```

일반 PC용 compose.local.yaml은 클라우드 전용 CA 경로를 요구하지 않는다. 회사 프록시/별도 CA가 필요한 환경은 기존 compose.yaml의 CA build secret 및 runtime mount 설정을 사용한다. TLS 검증은 유지한다. 이 구성은 브라우저 포트를 PC loopback에만 바인딩하므로 외부 서버/도메인 없이 사용할 수 있다.

Windows/macOS 실기기 실행은 이 workspace에서 직접 검증할 수 없으며, Linux Docker 및 같은 Compose 서비스 구조의 실행 결과와 구분한다.
