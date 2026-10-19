package com.ruleripple.backend.internal;

import org.springframework.data.jpa.repository.JpaRepository;

import java.time.LocalDate;
import java.util.List;

public interface LoanContractRepository extends JpaRepository<LoanContract, Long> {
    List<LoanContract> findByCustomerAgeBetweenAndMaturityAtAfter(int minAge, int maxAge, LocalDate after);
}
