package com.ruleripple.backend.common;

import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.multipart.support.MissingServletRequestPartException;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;
import java.util.NoSuchElementException;

/**
 * 에러 응답을 {error, message} 로 통일한다. 프론트 src/api/client.ts 는 이 형태 하나만 처리하면 된다.
 *   400 잘못된 입력 · 401 미인증 · 403 권한/승인 검증 실패 · 404 없음 · 409 상태 충돌(근거 검사 실패 제안 승인 등) · 413 파일 크기
 */
@RestControllerAdvice
public class ApiExceptionHandler {

    @ExceptionHandler(ResponseStatusException.class)
    ResponseEntity<Map<String, Object>> status(ResponseStatusException e) {
        HttpStatus s = HttpStatus.resolve(e.getStatusCode().value());
        return body(s == null ? HttpStatus.INTERNAL_SERVER_ERROR : s, String.valueOf(e.getReason()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<Map<String, Object>> invalid(MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .map(f -> f.getField() + ": " + f.getDefaultMessage()).findFirst().orElse("invalid request");
        return body(HttpStatus.BAD_REQUEST, msg);
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<Map<String, Object>> unreadable(HttpMessageNotReadableException e) {
        return body(HttpStatus.BAD_REQUEST, "요청 본문을 읽을 수 없습니다 (JSON 형식·enum 값 확인)");
    }

    @ExceptionHandler(MissingServletRequestPartException.class)
    ResponseEntity<Map<String, Object>> missingPart(MissingServletRequestPartException e) {
        return body(HttpStatus.BAD_REQUEST, e.getRequestPartName() + " 파일이 필요합니다");
    }

    @ExceptionHandler(MaxUploadSizeExceededException.class)
    ResponseEntity<Map<String, Object>> tooLarge(MaxUploadSizeExceededException e) {
        return body(HttpStatus.PAYLOAD_TOO_LARGE, "규정 파일은 1MB 이하여야 합니다");
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    ResponseEntity<Map<String, Object>> conflict(DataIntegrityViolationException e) {
        return body(HttpStatus.CONFLICT, "중복되었거나 제약 조건에 맞지 않는 데이터입니다");
    }

    @ExceptionHandler(NoSuchElementException.class)
    ResponseEntity<Map<String, Object>> notFound(NoSuchElementException e) {
        return body(HttpStatus.NOT_FOUND, "not found");
    }

    private static ResponseEntity<Map<String, Object>> body(HttpStatus s, String message) {
        return ResponseEntity.status(s).body(Map.<String, Object>of("error", s.name(), "message", message));
    }
}
