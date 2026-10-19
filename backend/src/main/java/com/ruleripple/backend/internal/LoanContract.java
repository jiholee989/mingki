package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.Period;

/** 기존 계약 · 신청 (data/business/loan_contracts.json). 읽기 전용. */
@Entity
@Table(name = "loan_contracts")
@Getter
@NoArgsConstructor
public class LoanContract {
    @Id
    @Column(name = "contract_id", length = 10)
    private String contractId;

    @Column(name = "product_id", nullable = false, length = 10)
    private String productId;

    @Column(name = "customer_id", nullable = false, length = 10)
    private String customerId;

    @Column(name = "birth_date", nullable = false)
    private LocalDate birthDate;

    /** 신청일. 나이 계산과 경과조치(시행일 이후 신청분부터 적용) 판단 기준. */
    @Column(name = "applied_at", nullable = false)
    private LocalDate appliedAt;

    @Column(name = "contracted_at")
    private LocalDate contractedAt;

    /** APPLIED | ACTIVE | REJECTED */
    @Column(nullable = false, length = 20)
    private String status;

    @Column(nullable = false)
    private long amount;

    @Column(name = "term_months", nullable = false)
    private int termMonths;

    @Column(name = "repayment_type", nullable = false, length = 20)
    private String repaymentType;

    @Column(name = "maturity_date")
    private LocalDate maturityDate;

    @Column(name = "extension_count", nullable = false)
    private int extensionCount;

    @Column(name = "annual_income", nullable = false)
    private long annualIncome;

    @Column(name = "dsr_at_approval", precision = 4, scale = 3)
    private BigDecimal dsrAtApproval;

    @Column(name = "senior_applied")
    private Boolean seniorApplied;

    @Column(name = "rate_discount_pp", precision = 3, scale = 2)
    private BigDecimal rateDiscountPp;

    @Column(name = "reject_reason", length = 50)
    private String rejectReason;

    @Column(columnDefinition = "text")
    private String note;

    /** 신청일 기준 만 나이. */
    public int ageAtApplication() {
        return Period.between(birthDate, appliedAt).getYears();
    }
}
