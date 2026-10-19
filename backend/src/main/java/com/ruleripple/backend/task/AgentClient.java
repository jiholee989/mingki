package com.ruleripple.backend.task;

import com.ruleripple.backend.config.RuleRippleProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.web.client.RestClientCustomizer;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/**
 * Spring → FastAPI Agent. 두 엔드포인트 모두 즉시 응답(202)하고, 실행 결과는
 * {callbackBaseUrl}/events · /requirements · /change-specs · /test-cases · /patches · /report 로 밀어준다.
 *
 *   POST {agent}/run    {taskId, threadId, title, documents:[{side, versionLabel, filename, sha256}], callbackBaseUrl}
 *   POST {agent}/resume {taskId, threadId, step, decision, approvalId, payload, callbackBaseUrl}
 *
 * 규정 원문은 GET {callbackBaseUrl}/documents 로 가져간다.
 */
@Slf4j
@Component
public class AgentClient {

    private final RestClient client;
    private final String callbackBase;

    public AgentClient(RuleRippleProperties props, RestClientCustomizer customizer) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(props.agent().connectTimeoutMs());
        factory.setReadTimeout(props.agent().readTimeoutMs());
        RestClient.Builder builder = RestClient.builder()
                .baseUrl(props.agent().baseUrl())
                .requestFactory(factory)
                .defaultHeader("X-Internal-Token", props.internal().token())
                .defaultHeader("X-Internal-Caller", "backend");
        customizer.customize(builder);
        this.client = builder.build();
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

    private String callbackBaseUrl(UUID taskId) {
        return callbackBase + "/internal/tasks/" + taskId;
    }
}
