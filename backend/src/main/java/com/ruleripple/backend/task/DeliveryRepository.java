package com.ruleripple.backend.task;

import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;
import java.util.UUID;

public interface DeliveryRepository extends JpaRepository<Delivery, Long> {
    List<Delivery> findByTaskIdOrderByIdAsc(UUID taskId);
}
