package com.ruleripple.backend.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "ruleripple")
public record RuleRippleProperties(Jwt jwt, Internal internal, Agent agent, Queue queue) {

    public record Jwt(String secret, int expiresMinutes) {}

    public record Internal(String token, String callbackBaseUrl) {}

    public record Agent(String baseUrl, int connectTimeoutMs, int readTimeoutMs) {}

    public record Queue(String exchange, String mainQueue, String retryQueue, String deadLetterQueue,
                        int retryDelayMs, int maxAttempts, double failureRate) {}
}
