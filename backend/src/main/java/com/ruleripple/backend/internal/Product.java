package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;
import org.hibernate.annotations.JdbcTypeCode;
import org.hibernate.type.SqlTypes;

import java.util.List;

/** 상품 마스터 (data/business/products.json). 읽기 전용. */
@Entity
@Table(name = "products")
@Getter
@NoArgsConstructor
public class Product {
    @Id
    @Column(name = "product_id", length = 10)
    private String productId;

    @Column(nullable = false, length = 100)
    private String name;

    @Column(columnDefinition = "text")
    private String description;

    @JdbcTypeCode(SqlTypes.JSON)
    @Column(name = "repayment_types", nullable = false, columnDefinition = "jsonb")
    private List<String> repaymentTypes;

    @Column(name = "min_term_months", nullable = false)
    private int minTermMonths;

    @Column(name = "max_term_months", nullable = false)
    private int maxTermMonths;

    @Column(nullable = false, length = 20)
    private String status;
}
