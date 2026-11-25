"""
Rate limiting (tiêu chí 7).

  • Mỗi API key tối đa RATE_LIMIT_PER_MINUTE request trong 60 giây (sliding window)
  • Vượt giới hạn → HTTP 429 kèm header Retry-After
  • State lưu trong Redis (sorted set) → mọi worker / instance dùng chung,
    vẫn còn sau khi restart agent
"""
import hashlib
import time
import uuid

import redis
from fastapi import HTTPException

from app.config import settings
from app.redis_client import r

WINDOW_SECONDS = 60


def _bucket(key: str) -> str:
    # Không lưu API key dạng plain text trong Redis
    return "ratelimit:" + hashlib.sha256(key.encode()).hexdigest()[:32]


def check_rate_limit(key: str) -> None:
    limit = settings.rate_limit_per_minute
    bucket = _bucket(key)
    now = time.time()
    try:
        pipe = r.pipeline(transaction=True)
        pipe.zremrangebyscore(bucket, 0, now - WINDOW_SECONDS)
        pipe.zcard(bucket)
        _, count = pipe.execute()

        if count >= limit:
            oldest = r.zrange(bucket, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(1, int(oldest[0][1] + WINDOW_SECONDS - now) + 1)
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded: {limit} requests per minute",
                headers={"Retry-After": str(retry_after)},
            )

        pipe = r.pipeline(transaction=True)
        pipe.zadd(bucket, {f"{now}-{uuid.uuid4().hex[:8]}": now})
        pipe.expire(bucket, WINDOW_SECONDS + 1)
        pipe.execute()
    except redis.RedisError:
        # Fail closed: không có Redis thì không kiểm soát được tốc độ
        raise HTTPException(status_code=503, detail="Rate limiter unavailable")
