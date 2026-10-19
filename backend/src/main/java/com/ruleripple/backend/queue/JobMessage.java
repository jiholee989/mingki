package com.ruleripple.backend.queue;

import java.util.UUID;

/** 큐에 실리는 메시지. 본문은 jobs 테이블에 있으므로 id 와 시도 횟수만 보낸다. */
public record JobMessage(UUID jobId, int attempt) {
    public JobMessage next() {
        return new JobMessage(jobId, attempt + 1);
    }
}
