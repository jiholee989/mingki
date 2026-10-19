package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDate;

/** 규정 키별 상품 적용값. 시행일 버전(effectiveFrom)으로 경과조치를 표현한다. 읽기 전용. */
@Entity
@Table(name = "product_rules")
@Getter
@NoArgsConstructor
public class ProductRule {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "product_id", nullable = false, length = 16)
    private String productId;

    @Column(name = "rule_key", nullable = false, length = 64)
    private String ruleKey;

    @Column(nullable = false, length = 64)
    private String value;

    @Column
    private String description;

    @Column(name = "regulation_ref", length = 64)
    private String regulationRef;

    @Column(name = "effective_from", nullable = false)
    private LocalDate effectiveFrom;
}
