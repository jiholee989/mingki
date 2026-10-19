package com.ruleripple.backend.internal;

import jakarta.persistence.*;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Table(name = "products")
@Getter
@NoArgsConstructor
public class Product {
    @Id
    @Column(length = 16)
    private String id;

    @Column(nullable = false, length = 64)
    private String name;

    @Column(nullable = false, length = 16)
    private String type;

    @Column(nullable = false)
    private boolean active;
}
