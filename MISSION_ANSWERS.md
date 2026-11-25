# Day 14 Lab — Mission Answers

> Môi trường chạy: Windows 11 + WSL2 Ubuntu, Docker Engine 29.8.1 (trong WSL), Python 3.11 (container `python:3.11-slim`).
> Mọi output dưới đây là output thật từ các lệnh đã chạy ngày 2026-11-25.

---

## Part 1: Localhost vs Production

### Exercise 1.1: Anti-patterns found (`01-localhost-vs-production/develop/app.py`)

| # | Anti-pattern | Dòng | Hậu quả |
|---|---|---|---|
| 1 | Hardcode secret: `OPENAI_API_KEY = "sk-hardcoded-..."` và `DATABASE_URL = "postgresql://admin:password123@..."` | 17–18 | Push lên GitHub là lộ key/mật khẩu; đổi key phải sửa code và deploy lại |
| 2 | Log ra secret: `print(f"[DEBUG] Using key: {OPENAI_API_KEY}")` | 34 | Key nằm trong log (đã thấy thật trong log container: `[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this`) |
| 3 | Dùng `print()` thay cho logging có cấu trúc, không có level | 33, 38 | Không lọc/tìm kiếm được trên log aggregator, không tắt được debug |
| 4 | Config cứng `DEBUG = True`, `MAX_TOKENS = 500` | 21–22 | Không đổi được giữa dev/staging/prod mà không sửa code |
| 5 | Không có `/health` (gọi thử trả **404**) | 42 | Platform không biết app chết để restart |
| 6 | `host="localhost"` | 51 | Trong container chỉ nhận kết nối nội bộ → bên ngoài không gọi được |
| 7 | `port=8000` cứng, không đọc `PORT` | 52 | Railway/Render cấp `PORT` động → app không nhận traffic |
| 8 | `reload=True` | 53 | Chế độ dev chạy trong production: tốn tài nguyên, watcher file |
| 9 | Không xử lý shutdown (không lifespan/SIGTERM) | — | Deploy/scale-down cắt ngang request đang chạy |
| 10 | `/ask` nhận `question` qua query string, không validate | 31 | Câu hỏi nằm trong URL → bị log lại ở proxy; không giới hạn độ dài |

### Exercise 1.2: Chạy bản develop

```text
$ curl -i -X POST "http://localhost:8000/ask?question=Hello"
HTTP/1.1 200 OK
{"answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận."}

$ curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP 422          # bản develop chỉ nhận query param

$ curl http://localhost:8000/health
HTTP 404          # không có health check

# log của server:
[DEBUG] Got question: Hello
[DEBUG] Using key: sk-hardcoded-fake-key-never-do-this     ← lộ secret
```

Chạy được nhưng **chưa production-ready**: lộ secret trong log, không health check, chỉ bind localhost, port cố định.

### Exercise 1.3: Comparison table

Bản production chạy thử: `POST /ask` (JSON) → 200, `GET /health` → `{"status":"ok","uptime_seconds":4.8,...}`, `GET /ready` → `{"ready":true}`.

| Feature | Develop | Production | Tại sao quan trọng? |
|---|---|---|---|
| Config | Hardcode trong code (`DEBUG=True`, key, DB URL) | `config.py` đọc env (`os.getenv`), `validate()` fail-fast nếu thiếu `AGENT_API_KEY` khi `ENVIRONMENT=production` | Cùng một image chạy ở mọi môi trường; secret không nằm trong git |
| Secret | Hardcode và in ra log | Đọc từ env, không log secret (chỉ log `question_length`) | Lộ key = mất tiền, phải revoke |
| Health check | Không có (404) | `/health` (liveness) + `/ready` (readiness, 503 khi chưa sẵn sàng) | Platform biết khi nào restart, LB biết khi nào route traffic |
| Logging | `print()` | JSON qua `logging` (`{"time":..,"level":..,"msg":..}`) | Parse được bằng Loki/Datadog, lọc theo level/field |
| Shutdown | Đột ngột | `lifespan` (startup/shutdown) + handler SIGTERM, uvicorn chờ request đang chạy | Rolling deploy không làm rơi request |
| Host/Port | `localhost:8000` cố định | `0.0.0.0` + `PORT` từ env | Chạy được trong container và trên PaaS |
| Reload/Debug | `reload=True` luôn bật | chỉ khi `DEBUG=true` | Production không chạy file watcher |
| Input | Query param, không validate | JSON body, kiểm tra `question` rỗng → 422 | API rõ ràng, lỗi có thông báo |
| CORS | Không có | `allowed_origins` từ env | Giới hạn origin được gọi API |

---

## Part 2: Docker

### Exercise 2.1: Dockerfile questions (`02-docker/develop/Dockerfile`)

1. **Base image:** `python:3.11`, bản đầy đủ (có compiler, header, tool), nên rất nặng.
2. **Working directory:** `/app` (`WORKDIR /app`).
3. **Vì sao COPY requirements.txt trước:** Docker cache theo từng layer. `requirements.txt` ít khi đổi, nên layer `pip install` được cache. Sửa code chỉ làm build lại từ lệnh `COPY app.py`, không phải cài lại dependencies. Nếu `COPY . .` trước thì đổi 1 dòng code cũng làm mất cache của `pip install`.
4. **CMD vs ENTRYPOINT:** `ENTRYPOINT` là chương trình cố định của container. `CMD` là lệnh/tham số mặc định, bị ghi đè khi `docker run image <lệnh khác>`. Khi có cả hai, `CMD` thành tham số của `ENTRYPOINT`. Ở đây dùng `CMD ["python", "app.py"]` (exec form) nên dễ ghi đè khi debug, và python là PID 1 nên nhận được SIGTERM.

### Exercise 2.2: Build và run

```text
$ docker build -f 02-docker/develop/Dockerfile -t my-agent:develop .
$ docker run -p 8000:8000 my-agent:develop
$ curl -X POST "http://localhost:8000/ask?question=What%20is%20Docker%3F"
{"answer":"Container là cách đóng gói app để chạy ở mọi nơi. Build once, run anywhere!"}
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":4.4,"container":true}
```

### Exercise 2.3: Multi-stage build và so sánh kích thước

- **Stage 1 (builder):** `python:3.11-slim` + cài `gcc`, `libpq-dev`, chạy `pip install --user -r requirements.txt` vào `/root/.local`. Stage này không được deploy.
- **Stage 2 (runtime):** `python:3.11-slim` sạch, tạo user `appuser` (non-root), chỉ `COPY --from=builder /root/.local`, `main.py` và `utils/`, có `HEALTHCHECK`, chạy uvicorn 2 workers.
- **Vì sao nhỏ hơn:** base slim thay vì full; gcc, header và apt cache chỉ nằm ở stage builder, không đi vào image cuối. Theo `docker history`, layer site-packages của image cuối chỉ còn 40.8 MB.

```text
$ docker images my-agent
IMAGE               ID             DISK USAGE   CONTENT SIZE
my-agent:advanced   1799da548bee        240MB         57.4MB
my-agent:develop    83e470e6d0d5       1.67GB          426MB

$ docker image inspect -f '{{.RepoTags}} {{.Size}}' my-agent:develop my-agent:advanced
[my-agent:develop] 1667788178
[my-agent:advanced] 239815532
```

- Develop: **1667.8 MB** (1.67 GB)
- Production: **239.8 MB**
- Chênh lệch: production nhỏ hơn **85.6 %** ((1667788178 − 239815532) / 1667788178)

(Image Part 6 của mình, `06-lab-complete/Dockerfile`, multi-stage với venv: **273 MB** theo script chấm.)

### Exercise 2.4: Docker Compose stack

```text
                 :80/:443
  client ──▶ ┌───────────┐   network "internal" (bridge)
             │  nginx    │──────────────┐
             └───────────┘              ▼
                                ┌──────────────┐
                                │ agent :8000  │ (không publish port ra host)
                                └──┬────────┬──┘
                       REDIS_URL   │        │  QDRANT_URL
                                   ▼        ▼
                         ┌────────────┐  ┌──────────────┐
                         │ redis:6379 │  │ qdrant:6333  │
                         └────────────┘  └──────────────┘
```

- 4 service: `agent` (build từ `02-docker/production/Dockerfile`, target `runtime`), `redis:7-alpine`, `qdrant/qdrant:v1.9.0`, `nginx:alpine`.
- Chỉ nginx publish port (80, 443). Các service gọi nhau bằng tên service qua DNS nội bộ của network `internal`. Agent `depends_on` redis và qdrant với `condition: service_healthy`, nên chỉ start khi hai service đó healthy.

```text
$ docker compose -p k5-day14-docker ps
k5-day14-docker-agent-1   Up 20 seconds (healthy)   8000/tcp
k5-day14-docker-nginx-1   Up 18 seconds             0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
k5-day14-docker-qdrant-1  Up 35 seconds (healthy)   6333-6334/tcp
k5-day14-docker-redis-1   Up 33 seconds (healthy)   6379/tcp

$ curl -i http://localhost/health
HTTP/1.1 200 OK
Server: nginx
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
{"status":"ok","uptime_seconds":15.7,"version":"2.0.0","timestamp":"2026-11-25T08:16:50.553315"}

$ curl -i -X POST http://localhost/ask -H "Content-Type: application/json" -d '{"question":"Explain microservices"}'
HTTP/1.1 200 OK
Server: nginx
{"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

Response đi qua Nginx (header `Server: nginx` cùng các security header do Nginx thêm vào).

---

## Part 3: Cloud Deployment

### Exercise 3.1 / 3.2: Deploy agent Part 6

- Nền tảng chính: **Railway (project `k5-day14-agent`, region iad)**
- URL: **https://agent-production-a3b95f67.up.railway.app**
- Chi tiết, lệnh test và ảnh: [DEPLOYMENT.md](DEPLOYMENT.md)

### So sánh `railway.toml` và `render.yaml` (`06-lab-complete/`)

| | `railway.toml` | `render.yaml` (Blueprint) |
|---|---|---|
| Định dạng | TOML, chỉ mô tả **build + deploy của 1 service** | YAML, mô tả **cả hạ tầng**: nhiều service (web + Key Value/Redis), plan, region |
| Build | `[build] builder = "DOCKERFILE"` | `runtime: docker`, `dockerfilePath`, `rootDir` (vì Render đọc từ gốc repo) |
| Health check | `[deploy] healthcheckPath = "/health"`, `healthcheckTimeout` | `healthCheckPath: /health` |
| Restart | `restartPolicyType = "ON_FAILURE"` | Render tự quản lý |
| Biến môi trường | **Không** khai báo trong file; đặt bằng `railway variables set` hoặc dashboard | Khai báo trong `envVars`; secret dùng `generateValue: true` (`AGENT_API_KEY`) hoặc `sync: false` (điền tay trên dashboard), không ghi giá trị |
| Redis | Thêm plugin/service Redis trên dashboard, rồi đặt `REDIS_URL` tham chiếu | Khai báo luôn service `type: keyvalue` và nối bằng `fromService ... property: connectionString` |
| Cách deploy | `railway up` từ CLI (upload thư mục hiện tại) | Push GitHub → New Blueprint → Render đọc file, auto-deploy mỗi lần push |
| Port | Railway inject `PORT`, CMD dùng `${PORT:-8000}` | Render inject `PORT` (mặc định 10000), CMD dùng `${PORT:-8000}` |

**Vì sao khác:** Railway thiên về CLI và cấu hình tối thiểu: file chỉ lo build/deploy, còn biến và service phụ quản lý trên dashboard. Render Blueprint là Infrastructure-as-Code: cả stack (web + Redis + env) nằm trong git, nên tái tạo được bằng một lần "New Blueprint".

### Exercise 3.3: Pipeline Cloud Run (`03-cloud-deployment/production-cloud-run/`)

1. **test:** Cloud Build chạy container `python:3.11-slim`, cài requirements và chạy `pytest tests/`. Test fail thì pipeline dừng.
2. **build:** `docker build` image, gắn 2 tag `gcr.io/$PROJECT_ID/ai-agent:$COMMIT_SHA` và `:latest`, dùng `--cache-from :latest` để tận dụng layer cache (chỉ chạy sau `test`).
3. **push:** đẩy mọi tag lên Container Registry.
4. **deploy:** `gcloud run deploy` image theo `$COMMIT_SHA` lên region `asia-southeast1`: min 1 / max 10 instance, 512Mi / 1 CPU, timeout 60s, env `ENVIRONMENT=production`, secret `OPENAI_API_KEY` lấy từ Secret Manager.
5. `service.yaml` mô tả cùng service theo dạng Knative khai báo: autoscaling theo `containerConcurrency: 80`, `livenessProbe` gọi `/health`, `startupProbe` gọi `/ready`, `AGENT_API_KEY` và `OPENAI_API_KEY` lấy từ `secretKeyRef`. Deploy bằng tag commit nên muốn rollback chỉ cần trỏ lại revision cũ.

---

## Part 4: API Security

### Exercise 4.1: API Key (`04-api-gateway/develop/app.py`, chạy với `AGENT_API_KEY=secret-key-123`)

- **Check ở đâu:** dependency `verify_api_key()` (dòng 39–54) đọc header `X-API-Key` qua `APIKeyHeader(auto_error=False)`, được gắn vào `/ask` bằng `Depends(verify_api_key)`.
- **Sai key:** thiếu key → **401** `Missing API key`; có key nhưng sai → **403** `Invalid API key.` (bản Part 6 của mình trả 401 cho cả hai, theo yêu cầu của script chấm).
- **Rotate key:** key đọc từ env `AGENT_API_KEY`, nên đổi biến môi trường trên platform rồi restart/redeploy là xong, không sửa code. Muốn rotate không downtime thì cho phép nhiều key cùng lúc (vd `AGENT_API_KEYS=old,new`), cấp key mới cho client, sau đó gỡ key cũ.

```text
$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 401 Unauthorized
{"detail":"Missing API key. Include header: X-API-Key: <your-key>"}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: wrong-key" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 403 Forbidden
{"detail":"Invalid API key."}

$ curl -i -X POST http://localhost:8000/ask -H "X-API-Key: secret-key-123" -H "Content-Type: application/json" -d '{"question":"Hello"}'
HTTP/1.1 200 OK
{"question":"Hello","answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."}
```

### Exercise 4.2: JWT (`04-api-gateway/production/`)

Flow: `POST /auth/token` (username/password) → server ký JWT HS256 với `JWT_SECRET`, payload `sub`, `role`, `iat`, `exp` (60 phút) → client gửi `Authorization: Bearer <token>` → `verify_token()` kiểm tra chữ ký và hạn mà không cần tra DB. Token hết hạn → 401, token sai → 403.

```text
$ curl -i -X POST http://localhost:8000/auth/token -H "Content-Type: application/json" -d '{"username":"student","password":"demo123"}'
HTTP/1.1 200 OK
{"access_token":"<TOKEN-ĐÃ-CHE>","token_type":"bearer","expires_in_minutes":60,"hint":"Include in header: Authorization: Bearer <TOKEN-ĐÃ-CHE>"}

$ curl -i -X POST http://localhost:8000/ask -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 401 Unauthorized
www-authenticate: Bearer
{"detail":"Authentication required. Include: Authorization: Bearer <token>"}

$ curl -i -X POST http://localhost:8000/ask -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"question":"Explain JWT"}'
HTTP/1.1 200 OK
{"question":"Explain JWT","answer":"Tôi là AI agent được deploy lên cloud. Câu hỏi của bạn đã được nhận.","usage":{"requests_remaining":9,"budget_remaining_usd":1.9e-05}}
```

### Exercise 4.3: Rate limiting (`rate_limiter.py`)

- **Thuật toán:** sliding window log, mỗi user một `deque` timestamp; bỏ timestamp cũ hơn 60s, đếm số còn lại.
- **Limit:** user thường **10 req/phút**, admin **100 req/phút**.
- **Bypass cho admin:** `/ask` chọn limiter theo `role` trong JWT: `rate_limiter_admin if role == "admin" else rate_limiter_user`. Admin (`teacher`) dùng bucket 100/phút.
- **Hạn chế:** state nằm trong RAM của process, nên nhiều instance/worker mỗi cái đếm riêng và restart là mất. Part 6 của mình chuyển sang Redis sorted set.

Vòng lặp 20 request bằng token `student` (request thứ nhất đã gọi ở 4.2):

```text
Request 1 -> HTTP 200
...
Request 9 -> HTTP 200
Request 10 -> HTTP 429
...
Request 20 -> HTTP 429

$ curl -i ... (request 21)
HTTP/1.1 429 Too Many Requests
x-ratelimit-limit: 10
x-ratelimit-remaining: 0
retry-after: 59
{"detail":{"error":"Rate limit exceeded","limit":10,"window_seconds":60,"retry_after_seconds":59}}
```

Tổng cộng 10 request thành công trong 60 giây (1 ở 4.2 + 9 trong vòng lặp), từ request thứ 11 trở đi bị 429.

### Exercise 4.4: Cost guard

**Bản mẫu (`04-api-gateway/production/cost_guard.py`):** đếm token in-memory theo user và theo ngày; giá gpt-4o-mini ($0.15/1M input, $0.60/1M output); user vượt $1/ngày → **402**, toàn hệ thống vượt $10/ngày → **503**; cảnh báo khi dùng 80%. `/me/usage` sau 10 request: `cost_usd: 0.000191`.

**Cách mình làm trong Part 6 (`06-lab-complete/app/cost_guard.py`):**

1. `check_budget()` được gọi **trước** khi gọi LLM: đọc 2 key Redis `cost:daily:YYYY-MM-DD` và `cost:monthly:YYYY-MM` (UTC) bằng một lệnh `MGET`. Nếu ≥ `DAILY_BUDGET_USD` hoặc ≥ `MONTHLY_BUDGET_USD` thì trả **402 Payment Required**.
2. `record_cost(input_tokens, output_tokens)` được gọi **sau** khi LLM trả lời: tính `cost = in/1000 × 0.00015 + out/1000 × 0.0006`, rồi `INCRBYFLOAT` cả 2 key trong một pipeline transaction (atomic, an toàn khi nhiều worker). Key ngày có TTL 2 ngày, key tháng 32 ngày, nên tự "reset" sang kỳ mới mà không cần cron.
3. State nằm trong Redis nên mọi worker/instance dùng chung một ngân sách và restart không mất. Redis lỗi lúc check thì trả 503 (fail closed: thà từ chối còn hơn tiêu tiền không kiểm soát).
4. Rate limit bảo vệ **tốc độ** (chống spam/DoS), cost guard bảo vệ **tiền** (nhiều client gọi chậm nhưng đều đặn vẫn có thể đốt hết budget). Cần cả hai.

---

## Part 5: Scaling & Reliability

### Exercise 5.1: Health checks (`05-scaling-reliability/develop`)

```text
$ curl http://localhost:8000/health
{"status":"ok","uptime_seconds":4.7,"version":"1.0.0","environment":"development",...,"checks":{"memory":{"status":"ok","used_percent":25.6}}}
$ curl http://localhost:8000/ready
{"ready":true,"in_flight_requests":1}
```

- **Liveness `/health`:** "process còn sống không?". Fail thì platform **restart** container. Không được phụ thuộc Redis/DB, nếu không Redis chết sẽ kéo theo restart hàng loạt mà chẳng giải quyết được gì.
- **Readiness `/ready`:** "có nhận traffic được không?". Fail (503) thì LB **ngừng route** tới instance đó nhưng không restart. Kiểm tra dependency (Redis) và cờ `is_ready` (đang khởi động hoặc đang tắt).

### Exercise 5.2: Graceful shutdown

Gửi request `/ask` rồi gửi ngay SIGTERM cho container (`docker kill -s TERM`, tương đương `kill -TERM $PID`):

```text
in-flight request result: {"answer":"Agent đang hoạt động tốt! (mock response) Hỏi thêm câu hỏi đi nhé."} [HTTP 200]
exit code: 0
INFO:     "POST /ask?question=Long%20task HTTP/1.1" 200 OK
INFO:     Shutting down
INFO:     Waiting for application shutdown.
INFO 🔄 Graceful shutdown initiated...
INFO ✅ Shutdown complete
INFO:     Application shutdown complete.
INFO:     Finished server process [1]
```

Request đang chạy vẫn hoàn thành (200), process thoát với exit code 0. Uvicorn bắt SIGTERM: ngừng accept kết nối mới, chờ request in-flight xong, chạy phần shutdown của `lifespan` (app đợi `_in_flight_requests == 0` tối đa 30s), rồi thoát.

### Exercise 5.3: Stateless design

`05-scaling-reliability/production/app.py` lưu session/history trong Redis (`session:{id}`, `setex` TTL 1 giờ) thay vì dict trong RAM. Mỗi instance có memory riêng, nên nếu giữ state trong RAM thì request sau rơi vào instance khác sẽ mất history, và restart hay scale-down cũng mất luôn. Có Redis thì instance nào cũng phục vụ được bất kỳ request nào, nên scale ngang thoải mái.

### Exercise 5.4: Load balancing (`docker compose -p k5-day14-scaling up -d --build --scale agent=3`)

```text
k5-day14-scaling-agent-1   Up 23 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-2   Up 25 seconds (healthy)   8000/tcp
k5-day14-scaling-agent-3   Up 22 seconds (healthy)   8000/tcp
k5-day14-scaling-nginx-1   Up 21 seconds             0.0.0.0:8080->80/tcp
k5-day14-scaling-redis-1   Up 37 seconds (healthy)   6379/tcp
```

10 request `POST http://localhost:8080/chat`, trường `served_by` cho thấy chia **round-robin** đều cho 3 instance:

```text
instance-c9b365, instance-0d0155, instance-14e881, instance-c9b365, instance-0d0155,
instance-14e881, instance-c9b365, instance-0d0155, instance-14e881, instance-c9b365   (storage: redis)
```

Nếu 1 instance chết, Nginx đánh dấu upstream lỗi và chuyển request sang instance còn lại. Session vẫn còn vì nằm trong Redis.

### Exercise 5.5: Test stateless (`python test_stateless.py`)

```text
Session ID: e116580d-3194-4aca-906b-fc4fe55ed03d
Request 1: [instance-0d0155]  Q: What is Docker?
Request 2: [instance-14e881]  Q: Why do we need containers?
Request 3: [instance-c9b365]  Q: What is Kubernetes?
Request 4: [instance-0d0155]  Q: How does load balancing work?
Request 5: [instance-14e881]  Q: What is Redis used for?
Total requests: 5
Instances used: {'instance-0d0155', 'instance-c9b365', 'instance-14e881'}
✅ All requests served despite different instances!
--- Conversation History ---
Total messages: 10
✅ Session history preserved across all instances via Redis!
```

**Giải thích:** 5 câu của cùng một session lần lượt đi qua cả 3 instance, nhưng history đọc lại vẫn đủ 10 message (5 user + 5 assistant). Lý do là mỗi instance ghi và đọc cùng key `session:<id>` trong Redis, không instance nào giữ state riêng. Nếu lưu trong dict của process thì mỗi instance chỉ thấy phần history mà chính nó đã xử lý.

---

## Part 6: Final Project — output `check_production_ready.py`

Lệnh chạy trong WSL2 (`os.name == 'posix'`), Docker Engine 29.8.1, ngày 2026-11-25:

```bash
cd 06-lab-complete
python check_production_ready.py --public-url https://agent-production-a3b95f67.up.railway.app
```

### 📋 Checklist Deliverable

```text
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 44/44 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

<details>
<summary>Output đầy đủ (12 tiêu chí, 44 checks)</summary>

```text
================================================================
  Production Readiness Check — Day 14 Lab
================================================================

✅ 1. Dockerfile (multi-stage, < 500 MB)
     ✅ Dockerfile tồn tại
     ✅ requirements.txt tồn tại
     ✅ Multi-stage build (≥ 2 lệnh FROM)
     ✅ Base image gọn (slim / alpine / distroless) — stage cuối dùng python:3.11-slim
     ✅ Chạy bằng user non-root
     ✅ Có HEALTHCHECK
     ✅ Docker: build image thành công — 29s
     ✅ Docker: image < 500 MB — 273 MB
     ✅ Docker: container chạy được, GET /health → 200

✅ 2. docker-compose.yml (agent + redis)
     ✅ docker-compose.yml tồn tại
     ✅ Có service agent (build từ Dockerfile) + redis — services: agent, redis — đọc bằng docker compose config
     ✅ Service agent kết nối redis (REDIS_URL + depends_on)

✅ 3. .dockerignore
     ✅ .dockerignore tồn tại và có nội dung
     ✅ .dockerignore loại trừ .env (secrets)
     ✅ .dockerignore loại trừ __pycache__, venv

✅ 4. Health check endpoint (GET /health)
     ✅ Code có route /health
     ✅ Khi chạy: GET /health → 200 — uvicorn --workers 2

✅ 5. Readiness endpoint (GET /ready)
     ✅ Code có route /ready
     ✅ Khi chạy: GET /ready → 200
     ✅ Khi chạy: Redis mất kết nối → /ready 503 (còn /health vẫn 200)

✅ 6. API Key authentication
     ✅ Code đọc header X-API-Key
     ✅ Khi chạy: thiếu / sai API key → 401
     ✅ Khi chạy: API key đúng → 200

✅ 7. Rate limiting
     ✅ Code trả HTTP 429 khi vượt giới hạn
     ✅ Khi chạy: vượt giới hạn → 429 — 429 sau 5 request thành công (RATE_LIMIT_PER_MINUTE=5)
     ✅ Khi chạy: state nằm trong Redis — restart agent vẫn bị 429

✅ 8. Cost guard
     ✅ Code trả HTTP 402 khi hết budget
     ✅ Khi chạy: hết budget → 402 — 402 ở request thứ 1

✅ 9. Config từ environment variables
     ✅ app/config.py đọc biến môi trường
     ✅ .env.example liệt kê đủ biến cấu hình
     ✅ .env nằm trong .gitignore
     ✅ Không hard-code secret trong code
     ✅ Khi chạy: agent dùng AGENT_API_KEY và RATE_LIMIT_PER_MINUTE từ env

✅ 10. Structured logging
     ✅ Code ghi log dạng JSON
     ✅ Khi chạy: mọi dòng log của app là JSON hợp lệ — 17 dòng JSON

✅ 11. Graceful shutdown
     ✅ Code xử lý SIGTERM / lifespan shutdown
     ✅ Khi chạy: SIGTERM lúc đang có request → request vẫn 200, process tự thoát — exit code 0
     ✅ Docker: `docker stop` tắt êm (exit code 0, < 10s) — exit code 0, 2.9s

✅ 12. Public URL ready (Railway / Render config)
     ✅ Có railway.toml hoặc render.yaml (không chỉ toàn comment)
     ✅ railway.toml: builder + healthcheckPath = "/health"
     ✅ render.yaml: web service + healthCheckPath /health
     ✅ render.yaml: secret không ghi thẳng giá trị (generateValue / sync: false)
     ✅ App lắng nghe theo biến PORT do platform cấp
     ✅ Public URL: GET https://agent-production-a3b95f67.up.railway.app/health → 200

================================================================
  📋 Checklist Deliverable
     ✅ Dockerfile (multi-stage, < 500 MB)
     ✅ docker-compose.yml (agent + redis)
     ✅ .dockerignore
     ✅ Health check endpoint (GET /health)
     ✅ Readiness endpoint (GET /ready)
     ✅ API Key authentication
     ✅ Rate limiting
     ✅ Cost guard
     ✅ Config từ environment variables
     ✅ Structured logging
     ✅ Graceful shutdown
     ✅ Public URL ready (Railway / Render config)
----------------------------------------------------------------
  Result: 12/12 tiêu chí đạt · 44/44 checks passed
  🎉 PASS 12/12 — PRODUCTION READY! Deploy nào!
================================================================
```

</details>

Một số điểm chính: image cuối **273 MB** (`python:3.11-slim`, user `app` non-root); rate limit trả 429 sau 5 request khi `RATE_LIMIT_PER_MINUTE=5`, restart agent vẫn 429 vì state nằm trong Redis; mất Redis thì `/ready` trả 503 còn `/health` vẫn 200; `docker stop` tắt êm trong 2.9 s với exit code 0.

---

## AI log

| # | Hỏi AI gì | AI trả về gì | Mình tự sửa / kiểm tra thế nào |
|---|---|---|---|
| 1 | Dùng Claude Code (Claude Opus) để đọc repo và lên plan làm bài theo RUBRIC/CHECKPOINTS | Plan theo thứ tự ưu tiên: Part 6 → deploy → Part 1/2/4/5 → Part 7 | Đối chiếu plan với RUBRIC.md và CHECKPOINTS.md |
| 2 | Nhờ Claude Code viết các TODO Part 6 (`config.py`, `auth.py`, `redis_client.py`, `rate_limiter.py`, `cost_guard.py`, `main.py`, Dockerfile, compose, `.dockerignore`, `.env.example`, `railway.toml`, `render.yaml`) | Code hoàn chỉnh: rate limit bằng Redis sorted set, cost guard bằng `INCRBYFLOAT` theo ngày/tháng, log JSON, lifespan, Dockerfile multi-stage non-root | Chạy `check_production_ready.py` (static, runtime trong Linux, bản đầy đủ trong WSL); tự `docker stop` đo thời gian tắt và exit code; đọc lại từng file để giải thích được |
| 3 | Nhờ Claude Code chạy các ví dụ Part 1, 2, 4, 5 trong WSL/Docker và tóm tắt output | Output thật của curl, `docker images`, `test_stateless.py` | Số MB, mã HTTP, tên instance lấy nguyên từ output lệnh, không chỉnh sửa |
| 4 | Nhờ Claude Code chạy load test / eval Part 7 và đề xuất tài liệu thêm vào `KNOWLEDGE_BASE` cho 2 câu sai | 2 entry mới (JWT vs API key, Kubernetes HPA) | Chạy lại eval: 23/23, không regression; kiểm tra keyword mới không trùng câu khác trong golden dataset |
| 5 | Nhờ Claude Code chạy Part 7 Bước 2 (stack Prometheus/Grafana/Jaeger, Locust scale 1 và 3, thí nghiệm alert A + B) và tìm trace chậm/lỗi qua Jaeger API | CSV Locust, thời điểm pending/firing của alert, 2 `trace_id` kèm dòng log JSON tương ứng | Đối chiếu số trong BENCHMARK_REPORT.md với `scale_*_stats.csv`; grep đúng `trace_id` trong log agent |
| 6 | Hỏi Claude Code vì sao agent trong stack Part 7 crash (`No module named 'uvicorn'`, Nginx 502) | Nguyên nhân: user `agent` có home `/app` nên Python không thấy packages ở `/home/agent/.local`; đề xuất thêm `ENV PYTHONUSERBASE` vào `production/Dockerfile` | Rebuild stack, `/ask` trả 200, Locust chạy không còn 502 |
| 7 | Nhờ Claude Code chụp 6 ảnh trong `screenshots/` (trừ `dashboard.png` mình tự chụp trên trình duyệt) | 4 ảnh Part 7 chụp bằng trình duyệt headless (Edge, Playwright) mở thẳng trang Prometheus/Grafana/Jaeger của stack đang chạy; `test.png`, `running.png` là output terminal thật (lệnh CP6, `railway service list`, `railway logs`) render thành ảnh | Mở xem lại từng ảnh: đúng 2 alert firing, đúng `trace_id`, mã HTTP 200/200/401/200 |
| 8 | Nhờ Claude Code deploy agent Part 6 lên Railway bằng CLI (sau khi mình tự `railway login`) | Project `k5-day14-agent` gồm service `agent` và Redis; key `AGENT_API_KEY` sinh ngẫu nhiên, chỉ lưu trên Railway | Chạy 4 lệnh tự kiểm CP6 và `check_production_ready.py --public-url`: PASS 12/12 |
| 9 | Nhờ Claude Code viết nháp các câu trả lời trong file này, `DEPLOYMENT.md` và `BENCHMARK_REPORT.md` từ output đã chạy, sau đó rà soát bỏ chú thích/hướng dẫn còn sót | Bản nháp các phần trả lời, phân tích và kết luận | Số liệu trong bài được đối chiếu với file JSON/CSV và output lệnh gốc |
