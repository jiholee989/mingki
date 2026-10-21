package com.ruleripple.backend.task;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AgentClientTest {

    @Test
    void agentErrorDetailIsReadable() {
        assertThat(AgentClient.detail("{\"detail\":\"승인 불가 제안: P002:DSR_LIMIT: 검증 실패\"}", "400 BAD_REQUEST"))
                .isEqualTo("승인 불가 제안: P002:DSR_LIMIT: 검증 실패");
        assertThat(AgentClient.detail("plain text", "400 BAD_REQUEST")).isEqualTo("plain text");
        assertThat(AgentClient.detail("", "400 BAD_REQUEST")).isEqualTo("400 BAD_REQUEST");
        assertThat(AgentClient.detail("{\"detail\":[{\"msg\":\"field required\"}]}", "422")).contains("field required");
    }
}
