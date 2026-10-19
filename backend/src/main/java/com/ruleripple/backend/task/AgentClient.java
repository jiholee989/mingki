package com.ruleripple.backend.task;

import com.ruleripple.backend.config.RuleRippleProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.web.client.RestClientCustomizer;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.Map;
import java.util.UUID;

/**
 * FastAPI Agent 호출. Agent 는 실행 중 진행 상황을 callbackUrl(/internal/tasks/{id}/events) 로 밀어준다.
 *
 * Agent 측 계약:
 *   POST {agent}/run    {taskId, threadId, regulationId, oldVersion, newVersion, question, callbackUrl}
 *   POST {agent}/resume {taskId, threadId, step: REVIEW|PUBLISH, decision: APPROVE|REJECT, payload, callbackUrl}
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

    public void run(AnalysisTask task) {
        Map<String, Object> body = Map.<String, Object>of(
                "taskId", task.getId().toString(),
                "threadId", task.getThreadId(),
                "regulationId", task.getRegulationId(),
                "oldVersion", task.getOldVersion(),
                "newVersion", task.getNewVersion(),
                "question", task.getQuestion() == null ? "" : task.getQuestion(),
                "callbackUrl", callbackUrl(task.getId()));
        client.post().uri("/run").body(body).retrieve().toBodilessEntity();
        log.info("agent run requested task={}", task.getId());
    }

    public void resume(AnalysisTask task, Approval.Step step, Approval.Decision decision, Map<String, Object> payload) {
        Map<String, Object> body = Map.<String, Object>of(
                "taskId", task.getId().toString(),
                "threadId", task.getThreadId(),
                "step", step.name(),
                "decision", decision.name(),
                "payload", payload == null ? Map.<String, Object>of() : payload,
                "callbackUrl", callbackUrl(task.getId()));
        client.post().uri("/resume").body(body).retrieve().toBodilessEntity();
        log.info("agent resume requested task={} step={} decision={}", task.getId(), step, decision);
    }

    private String callbackUrl(UUID taskId) {
        return callbackBase + "/internal/tasks/" + taskId + "/events";
    }
}
