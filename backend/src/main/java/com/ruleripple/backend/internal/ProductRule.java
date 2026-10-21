package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.time.LocalDate;
import java.util.List;

/**
 * 상품별 규칙값 (data/business/product_rules.json). 읽기 전용.
 * 경과조치는 기존 행을 effectiveTo 로 닫고 새 effectiveFrom 행을 추가해 표현한다.
 */
@Entity
@Table(name = "product_rules")
@Getter
@NoArgsConstructor
public class ProductRule {
    @Id
    @Column(name = "rule_id", length = 10)
    private String ruleId;

    @Column(name = "product_id", nullable = false, length = 10)
    private String productId;

    @Column(name = "rule_key", nullable = false, length = 50)
    private String ruleKey;

    @Column(nullable = false, length = 50)
    private String value;

    /** ratio | percent_point | krw | age | score | bool */
    @Column(nullable = false, length = 20)
    private String unit;

    @Column(name = "effective_from", nullable = false)
    private LocalDate effectiveFrom;

    /** null 이면 끝나는 날이 없다. 유효 여부는 isValidOn 으로 판단한다. */
    @Column(name = "effective_to")
    private LocalDate effectiveTo;

    /** 이 규칙이 따르는 규정 조항 {regulation_id}/{article_id}. 비어 있으면 상품 자체 기준이거나 미확인. */
    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "basis_articles", nullable = false, columnDefinition = "jsonb")
    private List<String> basisArticles;

    /** day 에 유효한 행인가. effectiveTo 가 null 이어도 시작 전이면 유효하지 않다. */
    public boolean isValidOn(LocalDate day) {
        return !effectiveFrom.isAfter(day) && (effectiveTo == null || !effectiveTo.isBefore(day));
    }
}
