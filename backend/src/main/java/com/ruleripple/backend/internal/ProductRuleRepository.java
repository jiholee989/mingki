package com.ruleripple.backend.internal;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface ProductRuleRepository extends JpaRepository<ProductRule, Long> {
    List<ProductRule> findByProductIdOrderByRuleKeyAscEffectiveFromDesc(String productId);
    List<ProductRule> findByRuleKeyOrderByProductIdAscEffectiveFromDesc(String ruleKey);
    List<ProductRule> findByProductIdAndRuleKeyAndEffectiveToIsNull(String productId, String ruleKey);
}
