package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDate;

/** 규정 키 → 상품별 적용값. 경과조치는 effective_from / effective_to 로 표현. */
@Entity
@Table(name = "product_rules")
@Getter
@Setter
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

    @Column(name = "value_type", nullable = false, length = 16)
    private String valueType;

    @Column(name = "regulation_id", length = 64)
    private String regulationId;

    @Column(name = "regulation_article", length = 32)
    private String regulationArticle;

    @Column(name = "effective_from", nullable = false)
    private LocalDate effectiveFrom;

    @Column(name = "effective_to")
    private LocalDate effectiveTo;
}
