package com.ruleripple.backend.auth;

/** SecurityContext principal. 역할은 없다. 로그인한 사용자는 모두 같은 일을 할 수 있다. */
public record AuthUser(Long id, String username, String displayName) {}
