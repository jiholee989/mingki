package com.ruleripple.backend.task;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.ruleripple.backend.config.RuleRippleProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.HttpStatusCodeException;
import org.springframework.web.client.RestClient;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Spring → FastAPI Agent. 세 엔드포인트 모두 즉시 응답(202)하고, 실행 결과는
 * {callbackBaseUrl}/events · /requirements · /proposals · /report 로 밀어준다.
 *
 *   POST {agent}/run    {taskId, threadId, title, documents:[{side, versionLabel, filename, sha256}], callbackBaseUrl}
 *   POST {agent}/resume {taskId, threadId, step, decision, approvalId, payload, callbackBaseUrl}
 *   POST {agent}/continue {taskId, threadId, callbackBaseUrl}   도중에 멈춘 작업 이어가기 (Agent 가 409 면 이어갈 게 없음)
 *
 * 규정 원문은 GET {callbackBaseUrl}/documents 로 가져간다.
 */
@Slf4j
@Component
public class AgentClient {

    private static final ObjectMapper JSON = new ObjectMapper();

    private final RestClient client;
    private final String callbackBase;

    /**
     * Boot 가 주는 RestClient.Builder (prototype) 를 받는다. 등록된 RestClientCustomizer 가 모두 적용된 상태다.
     * (RestClientCustomizer 를 직접 주입하면 Boot 자체 customizer 빈들과 겹쳐 NoUniqueBeanDefinitionException)
     */
    public AgentClient(RuleRippleProperties props, RestClient.Builder builder) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(props.agent().connectTimeoutMs());
        factory.setReadTimeout(props.agent().readTimeoutMs());
        this.client = builder
                .baseUrl(props.agent().baseUrl())
                .requestFactory(factory)
                .defaultHeader("X-Internal-Token", props.internal().token())
                .defaultHeader("X-Internal-Caller", "backend")
                .build();
        this.callbackBase = props.internal().callbackBaseUrl();
    }

    public void run(AnalysisTask task, List<RegulationDocument> docs) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("taskId", task.getId().toString());
        body.put("threadId", task.getThreadId());
        body.put("title", task.getTitle());
        body.put("documents", docs.stream().map(d -> Map.<String, Object>of(
                "side", d.getSide().name(),
                "versionLabel", d.getVersionLabel(),
                "filename", d.getFilename(),
                "sha256", d.getSha256())).toList());
        body.put("callbackBaseUrl", callbackBaseUrl(task.getId()));
        client.post().uri("/run").body(body).retrieve().toBodilessEntity();
        log.info("agent run requested task={}", task.getId());
    }

    public void resume(AnalysisTask task, Approval approval) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("taskId", task.getId().toString());
        body.put("threadId", task.getThreadId());
        body.put("step", approval.getStep().name());
        body.put("decision", approval.getDecision().name());
        body.put("approvalId", approval.getId());
        body.put("comment", approval.getComment());
        body.put("payload", approval.getPayload());
        body.put("callbackBaseUrl", callbackBaseUrl(task.getId()));
        client.post().uri("/resume").body(body).retrieve().toBodilessEntity();
        log.info("agent resume requested task={} step={} decision={}", task.getId(), approval.getStep(), approval.getDecision());
    }

    /** 동기 호출. Agent 의 409(이어갈 게 없음) · 연결 실패를 호출한 쪽이 그대로 사용자에게 돌려준다. */
    public void continueTask(AnalysisTask task) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("taskId", task.getId().toString());
        body.put("threadId", task.getThreadId());
        body.put("callbackBaseUrl", callbackBaseUrl(task.getId()));
        client.post().uri("/continue").body(body).retrieve().toBodilessEntity();
        log.info("agent continue requested task={} status={}", task.getId(), task.getStatus());
    }

    /** Agent 오류 응답에서 사람이 읽을 사유를 꺼낸다. FastAPI 는 {"detail": "..."} 로 돌려준다. */
    public static String detail(HttpStatusCodeException e) {
        return detail(e.getResponseBodyAsString(), e.getStatusCode().toString());
    }

    static String detail(String body, String fallback) {
        if (body == null || body.isBlank()) return fallback;
        try {
            JsonNode d = JSON.readTree(body).get("detail");
            if (d != null && d.isTextual()) return d.asText();
        } catch (Exception ignored) {
            // JSON 이 아니면 본문 그대로
        }
        return body;
    }

    private String callbackBaseUrl(UUID taskId) {
        return callbackBase + "/internal/tasks/" + taskId;
    }
}
