package com.ruleripple.backend.auth;

/** SecurityContext principal. */
public record AuthUser(Long id, String username, String displayName, User.Role role) {
    public boolean isLead() {
        return role == User.Role.LEAD;
    }
}
