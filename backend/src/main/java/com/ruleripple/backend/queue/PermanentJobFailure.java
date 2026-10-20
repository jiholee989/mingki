package com.ruleripple.backend.queue;

/** 다시 해도 결과가 같은 실패. 워커가 재시도하지 않고 바로 DEAD 로 보낸다. */
public class PermanentJobFailure extends RuntimeException {
    public PermanentJobFailure(String message) {
        super(message);
    }
}
