package com.ruleripple.backend.auth;

/** SecurityContext principal. */
public record AuthUser(Long id, String username, String displayName, User.Role role) {
    public boolean isOfficer() {
        return role == User.Role.OFFICER;
    }

    public boolean isDeveloper() {
        return role == User.Role.DEVELOPER;
    }
}
