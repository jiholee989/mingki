package com.ruleripple.backend.config;

import org.springframework.boot.web.client.RestClientCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class RestClientConfig {
    /** 확장 지점: 공통 로깅·trace_id 헤더 등을 여기서 붙인다. */
    @Bean
    RestClientCustomizer restClientCustomizer() {
        return builder -> builder.defaultHeader("User-Agent", "rule-ripple-backend");
    }
}
