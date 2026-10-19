package com.ruleripple.backend.auth;

import com.ruleripple.backend.config.RuleRippleProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.security.MessageDigest;
import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * /internal/** 은 docker network 안의 business-mcp / agent 만 호출한다.
 * X-Internal-Token 헤더가 설정값과 일치하면 ROLE_INTERNAL 을 부여한다.
 */
@Component
public class InternalTokenFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Internal-Token";
    private final byte[] expected;

    public InternalTokenFilter(RuleRippleProperties props) {
        this.expected = props.internal().token().getBytes(StandardCharsets.UTF_8);
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith("/internal/");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String token = request.getHeader(HEADER);
        if (token != null && MessageDigest.isEqual(expected, token.getBytes(StandardCharsets.UTF_8))) {
            String caller = request.getHeader("X-Internal-Caller"); // business-mcp | agent (로그용)
            var auth = new UsernamePasswordAuthenticationToken(
                    caller == null ? "internal" : caller, null, List.of(new SimpleGrantedAuthority("ROLE_INTERNAL")));
            SecurityContextHolder.getContext().setAuthentication(auth);
        }
        chain.doFilter(request, response);
    }
}
