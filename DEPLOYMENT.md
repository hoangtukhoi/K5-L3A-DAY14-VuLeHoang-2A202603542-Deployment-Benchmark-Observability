# Deployment Information

## Public URL

https://agent-production-a3b95f67.up.railway.app

## Platform

Railway. Deploy thư mục `06-lab-complete/` (agent Part 6) bằng `railway.toml`: builder `DOCKERFILE`, `healthcheckPath = "/health"`. Redis là service Redis riêng trong cùng project Railway.

## Test Commands

Trong các lệnh dưới, `BASE` là URL public; `AGENT_API_KEY` được export từ giá trị đã đặt trên Railway và không ghi vào repo. Mỗi lệnh chỉ in mã HTTP nên không lộ key:

```bash
export BASE=https://agent-production-a3b95f67.up.railway.app
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/health"     # 200
curl -sS -o /dev/null -w '%{http_code}\n' "$BASE/ready"      # 200
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -d '{"question":"Hello"}'   # 401
curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/ask" -H 'Content-Type: application/json' -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'   # 200
```

Kết quả thực tế:

```text
$ BASE=https://agent-production-a3b95f67.up.railway.app
$ curl -sS -o /dev/null -w "%{http_code}\n" "$BASE/health"
200
$ curl -sS -o /dev/null -w "%{http_code}\n" "$BASE/ready"
200
$ curl -sS -o /dev/null -w "%{http_code}\n" -X POST "$BASE/ask" -H "Content-Type: application/json" -d '{"question":"Hello"}'
401
$ curl -sS -o /dev/null -w "%{http_code}\n" -X POST "$BASE/ask" -H "Content-Type: application/json" -H "X-API-Key: $AGENT_API_KEY" -d '{"question":"Hello"}'
200

# Chạy lúc 2026-11-25 10:05 UTC. Log trên Railway xác nhận: /ask không key → 401, có key → 200 kèm event llm_call
```

### Health Check

```bash
curl "$BASE/health"
# {"status":"ok","environment":"production"}
curl "$BASE/ready"
# {"status":"ready"}      ← Redis trên Railway kết nối được
```

### API Test (with authentication)

```bash
curl -X POST "$BASE/ask" \
  -H "X-API-Key: $AGENT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "test", "question": "What is deployment?"}'
# {"question":"What is deployment?","answer":"Deployment là quá trình đưa code từ máy bạn lên server để người khác dùng được.","usage":{"input_tokens":3,"output_tokens":16,"cost_usd":1.005e-05}}
```

## Cách đã deploy

```bash
cd 06-lab-complete
railway init --name k5-day14-agent
railway add --database redis
railway add --service agent --variables "AGENT_API_KEY=<giá trị ngẫu nhiên, đã che>" --variables 'REDIS_URL=${{Redis.REDIS_URL}}'   --variables ENVIRONMENT=production --variables RATE_LIMIT_PER_MINUTE=10   --variables DAILY_BUDGET_USD=1.0 --variables MONTHLY_BUDGET_USD=10.0 --variables LOG_LEVEL=INFO
railway up --service agent --ci      # build bằng Dockerfile theo railway.toml
railway domain --service agent
```

Ghi chú: Railway CLI 5.75 cảnh báo `railway.toml` (Config as Code) sẽ được thay bằng `.railway/railway.ts`; file cũ vẫn dùng được tới 2026-12-01.

## Environment Variables Set

Các biến được đặt cho service `agent` bằng `railway add --variables` lúc tạo service (xem tab Variables trên dashboard Railway). Không giá trị nào nằm trong code hay trong git:

| Biến | Giá trị / nguồn |
|---|---|
| `AGENT_API_KEY` | secret ngẫu nhiên, chỉ lưu trên Railway |
| `REDIS_URL` | tham chiếu `${{Redis.REDIS_URL}}` từ service Redis của project |
| `ENVIRONMENT` | `production` |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `DAILY_BUDGET_USD` | `1.0` |
| `MONTHLY_BUDGET_USD` | `10.0` |
| `LOG_LEVEL` | `INFO` |
| `PORT` | Railway tự cấp; `CMD` của Dockerfile dùng `${PORT:-8000}` |

## Screenshots

- [Deployment dashboard](screenshots/dashboard.png)
- [Service running](screenshots/running.png)
- [Test results](screenshots/test.png)
