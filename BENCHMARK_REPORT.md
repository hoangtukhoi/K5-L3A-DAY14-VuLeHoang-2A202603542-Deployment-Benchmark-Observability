# Benchmark & Observability Report — Day 14

**Họ tên:** Vũ Lê Hoàng — 2A202603542
**Ngày chạy:** 2026-11-25
**Môi trường:** Windows 11 Pro + WSL2 Ubuntu, Docker Engine 29.8.1 chạy trong WSL. Bước 1 chạy agent và load test trong container `python:3.11-slim` (`--network host`); Bước 2 chạy Docker Compose stack `-p k5-day14-observability`.

Số liệu gốc: `reports/*.json` (Bước 1), `benchmark-results/scale_*_stats.csv` (Bước 2).

---

## 1. SLO của agent

| SLI | SLO | Lý do chọn ngưỡng này |
|---|---|---|
| p95 latency `/ask` | < 500 ms | Mock LLM mất ~120–200 ms mỗi call; 500 ms là ngưỡng người dùng chat vẫn thấy "nhanh", chừa chỗ cho retrieval và mạng. Dùng p95 vì average che mất tail latency |
| Error rate `/ask` | < 2 % | Upstream LLM có ~1 % lỗi ngẫu nhiên (`MOCK_ERROR_RATE=0.01`); 2 % cho error budget gấp đôi mức nền để spike ngắn không vi phạm. Alert đặt lỏng hơn (5 % trong 1 phút) để tránh alert fatigue |
| Accuracy trên golden dataset | ≥ 85 % (CI gate), không có regression | Dưới 85 % là người dùng thấy sai rõ; quality gate trong CI cũng chặn mọi câu từng đúng mà nay sai (regression) |

---

## 2. Benchmark hiệu năng (develop, `load_test.py`)

### 2.1 Concurrency vs latency (agent v2, 300 request mỗi mức)

| Concurrency | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Error rate | SLO |
|---|---|---|---|---|---|---|
| 1 | 3.81 | 187.8 | 552.3 | 1709.2 | 1.00 % | ❌ (p95 > 500) |
| 10 | 37.35 | 187.5 | 220.5 | 1695.9 | 0.67 % | ✅ |
| 50 | 114.57 | 202.1 | 268.4 | 1682.5 | 1.00 % | ✅ |
| 100 | 43.53 | 661.0 | 4529.8 | 4957.1 | 0.33 % | ❌ (p95 > 500) |

File: `reports/load_v2_c1.json`, `load_v2_c10.json`, `load_v2_c50.json`, `load_v2_c100.json`.

**Nhận xét:**

- Từ 1 → 10 → 50, RPS tăng gần tuyến tính (3.8 → 37 → 115) mà p50 gần như không đổi (~190–200 ms). Mock LLM là `asyncio.sleep`, nên một process uvicorn xử lý được nhiều request chờ I/O song song. Throughput ≈ concurrency / latency.
- Ở 100, RPS **giảm** còn 43.5 và p50 tăng lên 661 ms, p95 4.5 s: hệ thống đã **bão hoà**. Agent chạy 1 process, 1 event loop; phần CPU của mỗi request (parse JSON, Pydantic, Prometheus metrics, ghi log JSON) cộng với client load test chạy trên cùng máy khiến request phải xếp hàng chờ event loop. Thêm concurrency sau điểm này chỉ làm hàng đợi dài ra (latency tăng) chứ không tăng throughput.
- Ở concurrency 1, p95 552 ms vi phạm SLO dù hệ thống rảnh. 300 request tuần tự có ~3 % request chậm bất thường (~1.7 s); mẫu này rơi đúng vào vùng p95, nên kéo p95 vượt 500 ms. p99 ở mọi mức không tải đều ~1.7 s, chính là các request "slow" của mock LLM.

### 2.2 Tail latency (agent v2, `--requests 300 --concurrency 20`)

| `MOCK_SLOW_RATE` | avg (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| 0 | 190.0 | 219.2 | 239.1 |
| 0.03 (mặc định) | 245.7 | 245.0 | 1710.6 |
| 0.1 | 342.1 | 1690.8 | 1745.7 |

File: `reports/load_v2_slow_0.json`, `load_v2_slow_0.03.json`, `load_v2_slow_0.1.json`.

**Nhận xét:** Nhạy nhất là **p99**, sau đó tới p95. Từ 0 lên 0.03, avg chỉ tăng 29 % (190 → 246 ms), còn p99 tăng **7 lần** (239 → 1711 ms). Lên 0.1 thì 10 % request chậm, vượt ngưỡng 5 %, nên p95 cũng nhảy lên 1691 ms, trong khi avg mới 342 ms, nhìn vẫn "ổn". Average là trung bình cộng nên vài request rất chậm bị hàng trăm request nhanh pha loãng. Người dùng gặp request 1.7 s thì không quan tâm trung bình. Vì vậy SLO đặt theo p95/p99 mới phản ánh trải nghiệm của nhóm người dùng tệ nhất.

---

## 3. Benchmark chất lượng (develop, `eval/run_eval.py`)

| Chỉ số | Agent v1 | Agent v2 | Agent v2 (sau khi sửa KB) |
|---|---|---|---|
| Accuracy | 4.3 % (1/23) | 91.3 % (21/23) | 100 % (23/23) |
| Avg tokens / câu | 57.6 | 108.8 | 116.3 |
| Tổng cost (USD) | 0.000411 | 0.000757 | 0.000814 |
| Cost / câu đúng (USD) | 0.00041055 | 0.00003607 | 0.00003537 |
| Latency p50 / p95 (ms) | 158.8 / 184.3 | 198.3 / 218.8 | 192.8 / 216.6 |
| Quality gate | FAIL (`--min-accuracy 0.8`) | PASS (≥ 80 %, 0 regression so với v1) | PASS (`--min-accuracy 1.0`, 0 regression so với v2) |

File: `reports/eval_v1.json`, `reports/eval_v2.json`, `reports/eval_v2_fixed.json`.

**Những câu v2 trả lời sai ban đầu và cách mình sửa:**

| ID | Keyword bị thiếu | Mình đã sửa gì |
|---|---|---|
| security-02 ("JWT khác gì API key trong xác thực?") | `token`, `hết hạn`, `chữ ký` | KB không có tài liệu nào match câu hỏi. Thêm entry trigger `["jwt", "api key", "xác thực"]`: API key là chuỗi bí mật cố định, không tự hết hạn; JWT là token chứa claims và thời điểm hết hạn, ký bằng chữ ký số, server chỉ cần kiểm tra chữ ký |
| scaling-03 ("Kubernetes HPA scale dựa trên những chỉ số nào?") | `cpu`, `memory`, `custom metrics` | Thêm entry trigger `["hpa", "kubernetes", "autoscal"]`: HPA scale số pod dựa trên CPU, memory hoặc custom metrics (RPS, độ dài hàng đợi) |

Đã kiểm tra trước khi thêm: các keyword trigger mới không xuất hiện trong câu hỏi nào khác của golden dataset, nên không thể làm câu đang đúng chuyển sang retrieve nhầm tài liệu. Eval cuối báo `Câu bị regression: 0`. Phần sửa cũng được chép sang `production/utils/mock_llm.py` cho stack Docker.

**Nhận xét về trade-off chất lượng / chi phí / latency giữa v1 và v2:**

- v2 (RAG) tốn gần **gấp đôi token mỗi câu** (57.6 → 108.8) vì context retrieve được nhét vào prompt, tổng cost tăng 84 %. Latency p95 tăng ~34 ms (bước retrieval ~20 ms cộng với prompt dài hơn).
- Đổi lại accuracy tăng từ 4.3 % lên 91.3 %. Tính theo **cost / câu đúng**, v2 rẻ hơn v1 **11 lần** (0.000411 → 0.000036 USD). v1 rẻ mỗi câu nhưng gần như mọi câu đều sai, tức là trả tiền cho câu trả lời vô dụng. Vì vậy "cost / câu đúng" là thước đo công bằng hơn "cost / câu" khi so hai phiên bản.
- Sau khi sửa KB, cost tăng thêm 7.5 % (2 câu giờ có context dài) nhưng cost / câu đúng lại giảm nhẹ, nên đáng làm.

---

## 4. Observability stack (production)

Stack: `docker compose -p k5-day14-observability up -d --build` (nginx + agent + Prometheus + Grafana + Jaeger + Locust). Unit test alert rules: `promtool test rules /p/alert_rules_test.yml` → `SUCCESS`.

> Lỗi gặp khi bật stack: agent crash-loop `ModuleNotFoundError: No module named 'uvicorn'` và Nginx trả 502. Nguyên nhân là `production/Dockerfile` tạo user `agent` với home `/app` (`useradd -d /app`), nên Python tìm user site-packages ở `/app/.local`, trong khi packages được copy vào `/home/agent/.local`. Mình sửa bằng `ENV PYTHONUSERBASE=/home/agent/.local`, rebuild xong thì `/ask` trả 200.

### Trả lời Exercise 7.4

Số đo lúc chạy 100 user / 3 instance, PromQL với cửa sổ `[2m]`:

1. **p95 vs avg:** p95 `/ask` = **0.300 s**, avg = **0.244 s** (`sum(rate(..._sum)) / sum(rate(..._count))`). p95 chỉ cao hơn avg ~23 %, nhưng p99 trong Locust là **1700 ms**, tức tail latency nằm ở ~3 % request "slow" của mock LLM. Khoảng cách avg → p99 lớn nghĩa là phần lớn request nhanh nhưng có một nhóm nhỏ chậm gấp ~7 lần; nhìn avg sẽ không thấy nhóm này.
2. **Requests/s theo instance:** `sum by (instance) (rate(http_requests_total{route="/ask"}[2m]))` cho hai instance cũ **29.06** và **29.28 req/s**. Nginx chia gần như đều (round-robin). Instance thứ 3 mới vào giữa chừng nên chưa đủ dữ liệu trong cửa sổ 2 phút lúc mình query.
3. **Input tokens/s > output tokens/s:** **4520** input/s so với **2384** output/s. Agent v2 nhét system prompt và tài liệu retrieve được vào prompt, nên prompt dài hơn câu trả lời ngắn mà mock LLM sinh ra. Đây cũng là lý do RAG tốn tiền ở phía input.
4. **`curl http://localhost:8080/metrics`** trả **HTTP 404** từ Nginx: `nginx.conf` có `location = /metrics { return 404; }`. `/metrics` lộ thông tin nội bộ (route, số request, cost, version), nên chỉ Prometheus được scrape trực tiếp từng container trong mạng nội bộ `obs_net`, không đi qua cổng public.

Ngoài ra: response qua Nginx có header `x-trace-id: d56555428c6d9301b9f1bc4010722bb0` và `X-Served-By: 172.23.0.5:8000`.

### 4.1 Screenshot

- [x] Dashboard Grafana khi đang có tải: `screenshots/grafana-dashboard.png`
- [x] Trace chậm trong Jaeger: `screenshots/jaeger-slow-trace.png` (trace `e6b9345e248c29bc6ec0838a54f671d0`)
- [x] Trace lỗi trong Jaeger (có event `exception`): `screenshots/jaeger-error-trace.png` (trace `4f56865b82609c0e4cf1355be2ea2c28`)
- [x] Trang Alerts của Prometheus với 2 alert cùng **firing**: `screenshots/prometheus-alert-firing.png`

Ảnh Prometheus và Grafana chụp lúc ~09:42–09:47 UTC (16:42–16:47 giờ VN). Lúc đó vẫn giữ `.env` của thí nghiệm A + B và chạy lại Locust 30 user từ 09:24:39 UTC, vì đợt tải đầu đã hết hạn. Grafana ở thời điểm này: Error rate 20.03 %, Latency p95 1.91 s, 2 instance. Ảnh được chụp tự động bằng trình duyệt headless (Edge và Playwright) mở thẳng các trang của stack đang chạy; xem mục AI log trong `MISSION_ANSWERS.md`.

### 4.2 Thí nghiệm "phá hệ thống"

Cách làm: Locust headless 30 user chạy nền (bắt đầu 08:40:46 UTC). Lúc **T0 = 08:41:32 UTC**, sửa `.env` (`MOCK_ERROR_RATE=0.2`, `MOCK_SLOW_RATE=0.3`) rồi `docker compose -p k5-day14-observability up -d --scale agent=2`; agent được tạo lại sau 16.5 s. Thời gian đo bằng cách poll `GET /api/v1/alerts` của Prometheus mỗi 5 s. A và B chạy cùng lúc để có được ảnh 2 alert cùng firing.

| # | Thay đổi | Alert nào firing | Thời gian từ lúc đổi → firing | Panel nào phản ánh rõ nhất |
|---|---|---|---|---|
| A | `MOCK_ERROR_RATE=0.2` | `AgentHighErrorRate` (giá trị 19.0 %) | pending ở **+36 s**, firing ở **+96 s** (08:43:07 UTC) | Golden Signals → Error rate (đỏ); Req/s theo status (503 tăng) |
| B | `MOCK_SLOW_RATE=0.3` | `AgentHighLatencyP95` (p95 = 1.89 s) | pending ở **+31 s**, firing ở **+151 s** (08:44:02 UTC) | Latency p50/p95/p99/avg: p95, p99 vọt lên ~1.7–1.9 s, avg tăng ít hơn |
| C | `LLM_MODEL=mock-llm-large` | Không chạy riêng. Riêng `LLMCostBurnRateHigh` **đã firing** từ đợt Locust 100 user (activeAt 08:34:12 UTC, $2.74/giờ > $2/giờ) | — | Cost USD/giờ |
| D | `docker pause` 1 instance | Không làm | — | — |
| E | `AGENT_VERSION=v1` | Không làm (lý thuyết: không alert nào) | — | — |

**Phân tích:**

- Thời gian firing ≈ thời gian để cửa sổ `rate(...[1m])` "đầy" dữ liệu mới + thời gian `for`. A có `for: 1m`: pending khi error rate vượt 5 % (+36 s, do agent restart mất 16.5 s và rate 1 phút cần thêm mẫu), rồi firing sau đúng 60 s. B có `for: 2m` nên firing sau pending đúng 120 s. Muốn alert nhanh hơn thì giảm `for`, nhưng khi đó spike ngắn cũng gây báo động (alert fatigue).
- Phát hiện thêm: alert cost firing ngay trong lúc benchmark 100 user. Ngưỡng $2/giờ hợp với 30 user nhưng sẽ báo động khi tải tăng hợp lệ. Ngưỡng cost nên tính theo cost/request hoặc theo budget ngày thay vì một con số tuyệt đối.

**Phát hiện sự cố kiểu thí nghiệm E (đổi sang v1, không alert nào firing) trong production**

Lỗi chất lượng không làm metric hạ tầng (latency, error, up) thay đổi: v1 vẫn trả 200, thậm chí nhanh và rẻ hơn. Cách phát hiện:

1. **Quality gate trước deploy:** CI chạy `run_eval.py` trên golden dataset, accuracy < 85 % hoặc có regression thì exit code 1 và chặn merge/deploy (`.github/workflows/eval.yml`). Bước 1 cho thấy v1 chỉ đạt 4.3 %, nên sẽ bị chặn từ đầu.
2. **Eval định kỳ trên production** (canary/synthetic): cứ mỗi N phút gửi một tập câu hỏi golden vào endpoint thật, đẩy accuracy thành metric (vd `agent_eval_accuracy`) và đặt alert khi giảm.
3. **Metric proxy cho chất lượng:** retrieval hit ratio (v1 = 0), tỉ lệ câu trả lời generic, độ dài câu trả lời, feedback của người dùng; alert khi lệch khỏi baseline. Kèm alert khi `agent_info{version}` đổi bất thường.

### 4.3 Debug bằng trace

Trace chậm nhất trong 1 giờ (query Jaeger API v3, `duration_min=1500ms`, 450 trace chậm):

- `trace_id`: `e6b9345e248c29bc6ec0838a54f671d0` (08:38:04 UTC, lúc đang chạy Locust 100 user / 3 instance)
- Tổng thời gian: **3396.1 ms** (span `POST /ask`)
- Các span:

  ```text
  POST /ask                    3396.1 ms  100 %
  └── agent.run                1780.0 ms   52.4 %
      ├── agent.retrieve_context  86.6 ms    2.6 %
      └── chat mock-llm-small   1693.3 ms   49.9 %   (input_tokens=73, output_tokens=35)
  ```

- Span chiếm nhiều thời gian nhất **trong agent**: `chat mock-llm-small` (**1693.3 ms**, 49.9 % tổng, 95 % của `agent.run`). Đây là LLM "slow", không phải code của mình.
- Điểm đáng chú ý: `POST /ask` dài hơn `agent.run` **~1616 ms**. Khoảng này không thuộc span con nào, là thời gian request chờ trong process trước khi vào handler. Mỗi container chỉ có `cpus: 0.5` và 1 worker, nên ở 100 user event loop bị nghẽn CPU. Đây là nút thắt mà metric LLM latency không cho thấy, chỉ trace mới chỉ ra.
- Dòng log tương ứng (`grep e6b9345e248c29bc6ec0838a54f671d0` trên `docker compose -p k5-day14-observability logs agent`):

```json
{"ts": "2026-11-25T08:38:07.995363+00:00", "level": "INFO", "service": "observable-agent", "instance": "8125d4dda68f", "event": "llm_call", "trace_id": "e6b9345e248c29bc6ec0838a54f671d0", "span_id": "8a627698ac70ba44", "request_id": "3859ec8e3a16", "model": "mock-llm-small", "agent_version": "v2", "input_tokens": 73, "output_tokens": 35, "cost_usd": 3.2e-05, "llm_ms": 1692.8}
{"ts": "2026-11-25T08:38:07.995688+00:00", "level": "INFO", "service": "observable-agent", "instance": "8125d4dda68f", "event": "http_request", "trace_id": "e6b9345e248c29bc6ec0838a54f671d0", "span_id": "8a627698ac70ba44", "request_id": "3859ec8e3a16", "method": "POST", "route": "/ask", "status": 200, "ms": 3395.5}
```

Trace lỗi: `4f56865b82609c0e4cf1355be2ea2c28` (116.9 ms, HTTP 503). Span `chat mock-llm-small` và `agent.run` có status ERROR và event `exception`: `utils.mock_llm.LLMError: Upstream LLM error: 503 Service Unavailable (mock)`. Log:

```json
{"ts": "2026-11-25T08:38:27.858436+00:00", "level": "INFO", "service": "observable-agent", "instance": "8125d4dda68f", "event": "llm_error", "trace_id": "4f56865b82609c0e4cf1355be2ea2c28", "span_id": "ef27fcaae42ec3d7", "request_id": "b5a74bf8e90b", "error": "Upstream LLM error: 503 Service Unavailable (mock)"}
```

---

## 5. Benchmark scaling (production, Locust headless, 100 users, ramp 10/s, 2 phút)

Số của endpoint `POST /ask` (dòng `/ask` trong CSV; dòng Aggregated gồm cả `/health`):

| Số instance | RPS | p50 (ms) | p95 (ms) | p99 (ms) | Failures |
|---|---|---|---|---|---|
| 1 | 58.32 | 200 | 690 | 1700 | 73 / 6977 (1.05 %, toàn bộ 503 từ LLM) |
| 3 | 58.22 | 190 | 720 | 1700 | 63 / 6770 (0.93 %, toàn bộ 503 từ LLM) |

File: `benchmark-results/scale_1_stats.csv`, `benchmark-results/scale_3_stats.csv`.

**Giải thích kết quả:** Scale từ 1 lên 3 instance **không cải thiện** RPS, p95 hay p99.

- **RPS bị giới hạn bởi tải chứ không bởi server.** Locust là closed-loop: 100 user, mỗi user nghỉ 0.5–2 s (trung bình 1.25 s) sau mỗi request, nên tải tối đa ≈ 100 / (1.25 + 0.27) ≈ 66 req/s, khớp với ~64 req/s tổng đo được. Một instance đã phục vụ hết mức tải này, thêm instance thì không có thêm request để xử lý.
- **p99 = 1700 ms ở cả hai lần**, chính là các request "slow" của mock LLM (`MOCK_SLOW_RATE=0.03`, +1500 ms). p95 ~700 ms đến từ cùng nguồn. Đây là latency của **upstream LLM**: tăng số agent không làm LLM nhanh hơn. Nút thắt nằm ở LLM (panel LLM latency), không nằm ở agent.
- Scale có ích khi agent bị nghẽn CPU (trace 4.3 cho thấy có lúc chờ ~1.6 s trong process với `cpus: 0.5`) hoặc khi tăng tải thật (nhiều user hơn, ít think time hơn). Muốn giảm tail latency thì phải xử lý ở LLM: timeout + retry/hedging, cache câu hỏi lặp lại, streaming, hoặc model nhanh hơn.

---

## 6. Kết luận

- 3 điều mình học được về benchmark & observability:
  1. **Average nói dối.** Với 3 % request chậm, avg chỉ tăng 29 % còn p99 tăng 7 lần; SLO phải đặt theo p95/p99.
  2. **Đo đúng biến số.** Scale 1 → 3 instance không đổi gì vì nút thắt là LLM và tải closed-loop. Benchmark phải biết mình đang đo giới hạn của server, của client hay của upstream.
  3. **Metrics, traces và logs bổ sung cho nhau.** Metric báo p95 tăng; trace chỉ ra chậm ở span LLM hay do chờ trong process (~1.6 s không có span); `trace_id` nối sang đúng dòng log JSON. Còn lỗi chất lượng (v1) thì cả ba đều không bắt được, phải có eval.
- Nếu đưa agent này lên production thật, mình sẽ thêm:
  - Metric `agent_eval_accuracy` từ eval định kỳ + alert khi giảm; tỉ lệ retrieval hit, feedback người dùng.
  - Metric ở tầng Nginx/LB (5xx/504 của upstream, latency của LB) và synthetic check từ bên ngoài, vì lỗi 504 ở LB không hiện trong metric của agent.
  - Alert cost theo budget ngày (burn rate so với `DAILY_BUDGET_USD`) thay vì ngưỡng $/giờ cố định; alert saturation (`agent_in_flight_requests`, CPU throttling của container); alert SLO dạng multi-window burn rate thay cho ngưỡng tức thời.
