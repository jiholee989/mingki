package com.ruleripple.backend.task;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/** taskId 별 SseEmitter 레지스트리. 이벤트 저장 직후 연결된 클라이언트 전부에 전달한다. */
@Slf4j
@Component
public class SseBroadcaster {

    private static final long TIMEOUT_MS = 30 * 60 * 1000L;
    private final Map<UUID, List<SseEmitter>> emitters = new ConcurrentHashMap<>();

    public SseEmitter subscribe(UUID taskId) {
        SseEmitter emitter = new SseEmitter(TIMEOUT_MS);
        emitters.computeIfAbsent(taskId, k -> new CopyOnWriteArrayList<>()).add(emitter);
        Runnable remove = () -> {
            List<SseEmitter> list = emitters.get(taskId);
            if (list != null) list.remove(emitter);
        };
        emitter.onCompletion(remove);
        emitter.onTimeout(remove);
        emitter.onError(e -> remove.run());
        return emitter;
    }

    public void send(UUID taskId, TaskEvent event) {
        List<SseEmitter> list = emitters.get(taskId);
        if (list == null) return;
        for (SseEmitter emitter : list) {
            try {
                emitter.send(SseEmitter.event()
                        .id(String.valueOf(event.getSeq()))
                        .name(event.getType())
                        .data(Map.<String, Object>of("seq", event.getSeq(), "type", event.getType(), "payload", event.getPayload())));
                if ("DONE".equals(event.getType()) || "FAILED".equals(event.getType())) {
                    emitter.complete();
                }
            } catch (IOException | IllegalStateException e) {
                log.debug("sse send failed task={} : {}", taskId, e.getMessage());
                list.remove(emitter);
            }
        }
    }

    public void sendTo(SseEmitter emitter, TaskEvent event) throws IOException {
        emitter.send(SseEmitter.event()
                .id(String.valueOf(event.getSeq()))
                .name(event.getType())
                .data(Map.<String, Object>of("seq", event.getSeq(), "type", event.getType(), "payload", event.getPayload())));
    }
}
