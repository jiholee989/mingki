package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;

@Entity
@Table(name = "loan_contracts")
@Getter
@NoArgsConstructor
public class LoanContract {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "product_id", nullable = false, length = 16)
    private String productId;

    /** 마스킹된 식별자만 저장 (Guardrail). */
    @Column(name = "customer_ref", nullable = false, length = 32)
    private String customerRef;

    @Column(name = "customer_age", nullable = false)
    private int customerAge;

    @Column(nullable = false)
    private BigDecimal principal;

    @Column(name = "rate_pct", nullable = false)
    private BigDecimal ratePct;

    @Column(name = "contracted_at", nullable = false)
    private LocalDate contractedAt;

    @Column(name = "maturity_at", nullable = false)
    private LocalDate maturityAt;
}
