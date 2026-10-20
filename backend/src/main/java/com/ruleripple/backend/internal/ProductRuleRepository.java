package com.ruleripple.backend.internal;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ProductRuleRepository extends JpaRepository<ProductRule, String> {
    List<ProductRule> findByProductIdOrderByRuleKeyAscEffectiveFromDesc(String productId);

    List<ProductRule> findAllByOrderByRuleKeyAscProductIdAscEffectiveFromDesc();
}
