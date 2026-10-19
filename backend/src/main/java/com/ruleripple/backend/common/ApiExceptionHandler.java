package com.ruleripple.backend.common;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.NoSuchElementException;

/** 에러 응답을 {error, message} 로 통일. Vue 쪽에서 한 가지 형태만 처리하면 된다. */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(ResponseStatusException.class)
    ResponseEntity<Map<String, Object>> status(ResponseStatusException e) {
        return ResponseEntity.status(e.getStatusCode())
                .body(Map.<String, Object>of("error", e.getStatusCode().toString(), "message", String.valueOf(e.getReason())));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<Map<String, Object>> invalid(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .map(f -> f.getField() + ": " + f.getDefaultMessage()).findFirst().orElse("invalid request");
        return ResponseEntity.badRequest().body(Map.<String, Object>of("error", "BAD_REQUEST", "message", msg));
    }

    @ExceptionHandler(NoSuchElementException.class)
    ResponseEntity<Map<String, Object>> notFound(NoSuchElementException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.<String, Object>of("error", "NOT_FOUND", "message", "not found"));
    }
}
