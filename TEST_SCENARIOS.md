# 배포 전 테스트 시나리오

`scripts/gradio_app.py`를 배포하기 전, 아래 질문들을 직접 입력해 답변을 확인해 주세요.
전부 이번 세션에서 실제 검증된 문항(기대 답변이 이미 확인된 문항)이라 정답과 바로
비교할 수 있습니다.

## 실행 방법(로컬 확인용)

`scripts/gradio_app.py`가 `HWP_RAG_ANSWER_STRATEGY=multi_agent` + `gpt-oss:20b`
조합을 스크립트 안에서 직접 고정하므로(환경변수로 덮어쓸 수 없음 — "왜 이렇게
했는지"는 스크립트 상단 docstring 참고), 환경변수를 따로 안 붙여도 된다:

```bash
conda activate langc
cd hierarchical-md-rag
ollama serve &          # 이미 떠 있으면 생략
python scripts/gradio_app.py --port 7860
```

실행 즉시 Ollama/gpt-oss:20b 연결을 확인하고, 안 되면 바로 실패 사유를 출력하고
종료합니다(모호한 런타임 에러 대신).

**응답 시간 기대치**: 단일 사실 질문은 보통 10~30초, 비교 질문은 여러 단계를 거쳐 더
오래 걸릴 수 있습니다(1분 이상도 정상). #5/#6이 #1/#2보다 느려도 버그가 아닙니다.

## 테스트 문항

| # | 유형 | 질문 | 기대 답변 |
|---|---|---|---|
| 1 | 단일 사실 | SRT 감속기 모터피니언기어 구매 입찰의 낙찰자 결정 기준은 무엇인가요? | 예정가격의 82.495% 이상, 최저가격순, 적격심사, 종합평점 85점 이상 |
| 2 | 단일 사실(마감일) | 2026년 대전광역시립요양원 식자재 구매의 납품기한은 언제까지인가요? | 2026. 12. 31. |
| 3 | 2곳 비교(예산 숏컷 경로) | 쏘유팜과 영남영농조합법인의 히트펌프 물품 구매 중 예산이 더 큰 곳은 어디인가요? | 영남영농조합법인이 더 큼 (608,881,900원 vs 245,339,600원) |
| 4 | 3곳 비교(오늘 새로 고친 부분 — 꼭 확인) | 쏘유팜, 영남영농조합법인, 진주올팜의 히트펌프 물품 구매 중 예산이 가장 큰 곳은 어디인가요? | 영남영농조합법인이 최고(608,881,900원), 나머지 두 곳도 목록에 나와야 함 |
| 5 | 2단계 비교(multi_agent 자체 경로, 예산 숏컷 아님) | 장성경찰서 장애인승강기 설치공사(건축)와 (통신) 중 기초금액이 더 큰 공사는 무엇인가요? | 건축이 더 큼 (368,467,000원 vs 24,867,000원) |
| 6 | **알려진 미해결 사례** — 비교가 아닌 복합 질문 | SRT 감속기 모터피니언기어 구매 입찰의 낙찰자 결정 기준과 계약기간을 각각 알려주세요. | 두 사실 다 나와야 하나, 낙찰자 기준이 짧은 인용("조달청 물품구매적격심사 세부기준 제9조")으로만 나올 수 있음 — 우리가 "그 정도면 충분"으로 판단했던 사례, 직접 확인해 보세요 |
| 7 | 정직한 실패 확인 | 존재하지 않는 가상의 기관명으로 질문(예: "가나다주식회사의 계약기간은 언제인가요?") | "문서에서 확인되지 않습니다" 류의 정직한 실패만 나와야 함 — 절대 지어낸 답을 내면 안 됨 |

## 확인 후 체크리스트

- [ ] #1~#5 모두 기대 답변과 일치하는가
- [ ] #6에서 우려되는 수준의 답변인지, 아니면 "이 정도면 배포해도 된다" 수준인지 직접 판단
- [ ] #7에서 존재하지 않는 기관을 지어내서 답하지 않는가(환각 확인)
- [ ] 👍/👎 버튼이 정상 동작하고 `eval_resources/gradio_flagged/`에 기록이 남는가

---

# 실제 도메인 + HTTPS 배포 가이드

`--share`(72시간 임시 링크)가 아니라 실제 도메인으로 테스터에게 링크를 주고 싶을 때
쓰는 구성이다. 전체 그림:

```
인터넷 ── (443/80만 열림) ── nginx(리버스 프록시 + SSL 종료)
                                 │ (localhost만, 외부 비공개)
                                 ├── gradio_app.py (127.0.0.1:7860)
                                 └── ollama serve  (127.0.0.1:11434)
```

**핵심 원칙**: 인터넷에 직접 노출되는 건 nginx(80/443)뿐이어야 한다. Gradio
프로세스(7860)와 Ollama(11434)는 반드시 `127.0.0.1`에만 바인딩해서 외부에서 직접
접근 못 하게 막는다 — 특히 Ollama API는 인증이 없어서 그대로 열어두면 누구나 그
서버의 GPU/CPU로 무료 추론을 돌릴 수 있게 된다.

## 0) 사전 준비

- 도메인의 A 레코드가 이 서버의 공인 IP를 가리키도록 설정(DNS 전파는 수 분~수십 분
  걸릴 수 있음 — `dig <도메인>`으로 확인).
- 방화벽에서 80(HTTP), 443(HTTPS), 22(SSH)만 열고 나머지는 닫는다.
  ```bash
  sudo ufw allow 22/tcp
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw enable
  sudo ufw status  # 7860, 11434가 목록에 없어야 정상
  ```

## 1) Ollama 실행

Ollama 공식 설치 스크립트(`curl -fsSL https://ollama.com/install.sh | sh`)는 리눅스에서
보통 systemd 서비스(`ollama.service`)를 함께 설치한다. 먼저 이미 떠 있는지 확인:

```bash
systemctl status ollama          # active (running)이면 아래 등록 단계 생략
curl -s localhost:11434/api/tags # 응답 오면 이미 정상 동작 중
```

서비스가 없다면 직접 등록한다(재부팅 후에도 자동 기동):

```bash
sudo systemctl enable --now ollama
```

**바인딩 확인** — 기본값이 `127.0.0.1`이라 보통 안전하지만, `OLLAMA_HOST` 환경변수가
`0.0.0.0`으로 설정돼 있지 않은지 확인한다:

```bash
systemctl show ollama -p Environment   # OLLAMA_HOST=0.0.0.0가 보이면 반드시 제거
```

**병렬 처리(다중 사용자)**: `scripts/gradio_app.py`는 기본적으로 챗봇 인스턴스를
2개(`GRADIO_APP_POOL_SIZE`, 기본값 2) 준비해 테스터 2명까지는 동시에 응답을 생성할
수 있다. 하지만 이건 앱 쪽 큐일 뿐이고, Ollama 서버 자체도 `OLLAMA_NUM_PARALLEL`을
그만큼 올려주지 않으면 Ollama가 내부에서 다시 요청을 직렬화해 버려 체감 이득이 없다.
systemd로 띄운다면 override로 추가한다:

```bash
sudo systemctl edit ollama
```

편집기가 열리면 다음을 추가(저장하면 자동으로 override 파일 생성):

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=2"
```

```bash
sudo systemctl restart ollama
systemctl show ollama -p Environment   # OLLAMA_NUM_PARALLEL=2 확인
```

L4(24GB) 기준 모델(~14GB)을 빼면 ~10GB가 남는데, 병렬 슬롯마다 KV 캐시가 늘어나므로
2가 안전한 기본값이다. `GRADIO_APP_POOL_SIZE`와 `OLLAMA_NUM_PARALLEL`은 반드시 같은
값으로 맞출 것 — 한쪽만 올리면 남는 이득이 없거나(Ollama만 올림) 요청이 쌓이기만
한다(앱만 올림).

모델 pull(최초 1회, ~13GB):

```bash
ollama pull gpt-oss:20b
ollama list   # gpt-oss:20b가 보이면 완료
```

## 2) Gradio 앱을 systemd 서비스로 등록

SSH 세션이 끊겨도 계속 돌고, 크래시 시 자동 재시작되도록 systemd unit을 만든다.
`--host 127.0.0.1`로 바인딩해 nginx를 거치지 않은 직접 접근을 막는다.

`/etc/systemd/system/rag-gradio.service`:

```ini
[Unit]
Description=RAG Gradio test deployment
After=network.target ollama.service
Requires=ollama.service

[Service]
Type=simple
User=<실행할 사용자명>
WorkingDirectory=/home/<사용자>/project/hierarchical-md-rag
ExecStart=/home/<사용자>/miniconda3/envs/langc/bin/python scripts/gradio_app.py --host 127.0.0.1 --port 7860
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rag-gradio
sudo systemctl status rag-gradio      # active (running) 확인
journalctl -u rag-gradio -f           # 로그 실시간 확인(문제 생기면 여기부터 본다)
```

## 3) nginx 리버스 프록시 설정

Apache로도 가능하지만(`mod_proxy` + `mod_proxy_wstunnel` 활성화 필요), Gradio는
실시간 UI 업데이트에 WebSocket을 쓰기 때문에 nginx 쪽이 설정이 더 간단하고 표준적이라
nginx를 권장한다. 아래는 nginx 기준.

```bash
sudo apt install nginx   # 데비안/우분투 기준
```

`/etc/nginx/sites-available/rag-gradio`:

```nginx
server {
    listen 80;
    server_name <도메인>;

    location / {
        proxy_pass http://127.0.0.1:7860;
        proxy_http_version 1.1;

        # WebSocket 업그레이드 — 이거 빠지면 채팅 화면이 뜨긴 해도 답변이
        # 안 오거나 화면이 안 갱신된다(Gradio의 큐/스트리밍이 WebSocket 의존).
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # multi_agent 응답이 느릴 수 있으니(비교 질의 1분+) 타임아웃을 넉넉히
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/rag-gradio /etc/nginx/sites-enabled/
sudo nginx -t                 # 설정 문법 검사
sudo systemctl reload nginx
```

이 시점에서 `http://<도메인>`으로 접속되는지 먼저 확인(아직 HTTPS 아님).

## 4) Certbot으로 HTTPS 인증서 발급

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d <도메인>
```

`--nginx` 플러그인이 위에서 만든 서버 블록을 자동으로 찾아 443 리스너와 인증서
설정을 추가해 준다(대화형으로 이메일 입력, HTTP→HTTPS 리다이렉트 여부 질문 — 리다이렉트는
"예"로 해도 된다). 완료 후:

```bash
sudo certbot renew --dry-run   # 자동 갱신이 정상 동작하는지 확인(실제 갱신은 안 함)
```

인증서는 90일마다 자동 갱신되도록 certbot이 systemd timer(`certbot.timer`)를 이미
등록해 둔다 — 별도 cron 설정 불필요.

## 5) 최종 점검

- [ ] `https://<도메인>`으로 접속되고 인증서 경고가 없는가(브라우저 자물쇠 아이콘)
- [ ] `http://<도메인>`으로 접속 시 `https://`로 자동 리다이렉트되는가
- [ ] 외부에서 `curl http://<서버IP>:7860`, `curl http://<서버IP>:11434`가 **막혀야** 정상
      (방화벽에서 닫혀 있는지 서버 밖에서 재확인)
- [ ] `systemctl status ollama rag-gradio nginx` 셋 다 active (running)
- [ ] 재부팅 후에도 세 서비스가 자동으로 다시 뜨는가(`sudo reboot` 후 확인 — 테스트
      환경이면 한 번은 실제로 재부팅해 보는 걸 권장)
- [ ] `TEST_SCENARIOS.md` 위쪽 테스트 문항을 실제 도메인 URL로 한 번 더 확인
