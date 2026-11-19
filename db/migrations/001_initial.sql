-- =============================================================================
-- 001_initial.sql  —  Malenadu Resilience Impact Agent
-- MySQL 8.0+   utf8mb4   InnoDB
-- Run:  mysql -u <user> -p <database> < db/migrations/001_initial.sql
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `users` (
    `id`            INT UNSIGNED    NOT NULL AUTO_INCREMENT,
    `email`         VARCHAR(255)    NOT NULL,
    `password_hash` VARCHAR(72)     NOT NULL,
    `full_name`     VARCHAR(255)    NOT NULL,
    `role`          ENUM('citizen','coordinator') NOT NULL DEFAULT 'citizen',
    `is_active`     TINYINT(1)      NOT NULL DEFAULT 1,
    `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_users_email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- incidents
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `incidents` (
    `id`                   INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `reporter_id`          INT UNSIGNED NULL,
    `raw_text`             TEXT         NOT NULL,
    `location_name`        VARCHAR(255) NULL,
    `lat`                  DOUBLE       NULL,
    `lng`                  DOUBLE       NULL,
    `incident_type`        ENUM('flood','landslide','road_block','infrastructure','medical','other') NULL,
    `severity`             TINYINT      NULL COMMENT '1-5',
    `affected_households`  INT          NULL,
    `report_time`          DATETIME     NULL,
    `structured_json`      JSON         NULL,
    `status`               ENUM('pending','verified','duplicate','incomplete','rejected') NOT NULL DEFAULT 'pending',
    `created_at`           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_incidents_reporter` (`reporter_id`),
    KEY `idx_incidents_status`   (`status`),
    CONSTRAINT `fk_incidents_reporter` FOREIGN KEY (`reporter_id`)
        REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- verifications
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `verifications` (
    `id`                    INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `incident_id`           INT UNSIGNED NOT NULL,
    `is_duplicate`          TINYINT(1)   NOT NULL DEFAULT 0,
    `duplicate_of_id`       INT UNSIGNED NULL,
    `duplicate_similarity`  DOUBLE       NULL,
    `is_complete`           TINYINT(1)   NOT NULL DEFAULT 0,
    `missing_fields`        JSON         NULL,
    `has_conflict`          TINYINT(1)   NOT NULL DEFAULT 0,
    `conflict_detail`       TEXT         NULL,
    `status`                ENUM('pending','passed','duplicate','incomplete','conflict') NOT NULL DEFAULT 'pending',
    `coordinator_note`      TEXT         NULL,
    `reviewed_by_id`        INT UNSIGNED NULL,
    `created_at`            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_verifications_incident` (`incident_id`),
    KEY `idx_verifications_status` (`status`),
    CONSTRAINT `fk_verifications_incident`    FOREIGN KEY (`incident_id`)
        REFERENCES `incidents` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_verifications_duplicate`   FOREIGN KEY (`duplicate_of_id`)
        REFERENCES `incidents` (`id`) ON DELETE SET NULL,
    CONSTRAINT `fk_verifications_reviewer`    FOREIGN KEY (`reviewed_by_id`)
        REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- road_segments
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `road_segments` (
    `id`             INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    `osm_way_id`     BIGINT        NOT NULL,
    `name`           VARCHAR(255)  NULL,
    `highway_type`   VARCHAR(64)   NULL,
    `start_node_id`  BIGINT        NOT NULL,
    `end_node_id`    BIGINT        NOT NULL,
    `start_lat`      DOUBLE        NOT NULL,
    `start_lng`      DOUBLE        NOT NULL,
    `end_lat`        DOUBLE        NOT NULL,
    `end_lng`        DOUBLE        NOT NULL,
    `length_m`       DOUBLE        NULL,
    `blocked`        TINYINT(1)    NOT NULL DEFAULT 0,
    `created_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_road_segments_osm_way` (`osm_way_id`),
    KEY `idx_road_segments_start_node` (`start_node_id`),
    KEY `idx_road_segments_end_node`   (`end_node_id`),
    KEY `idx_road_segments_blocked`    (`blocked`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- villages
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `villages` (
    `id`           INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `osm_node_id`  BIGINT       NOT NULL,
    `name`         VARCHAR(255) NOT NULL,
    `lat`          DOUBLE       NOT NULL,
    `lng`          DOUBLE       NOT NULL,
    `population`   INT          NULL,
    `is_town`      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT 'population > 5000',
    `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_villages_osm_node` (`osm_node_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- accessibility_results
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `accessibility_results` (
    `id`                    INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `village_id`            INT UNSIGNED NOT NULL,
    `is_isolated`           TINYINT(1)   NOT NULL DEFAULT 0,
    `blocking_segment_ids`  JSON         NULL,
    `computed_at`           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_accessibility_village`  (`village_id`),
    KEY `idx_accessibility_isolated` (`is_isolated`),
    CONSTRAINT `fk_accessibility_village` FOREIGN KEY (`village_id`)
        REFERENCES `villages` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- relief_requests
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `relief_requests` (
    `id`                INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `incident_id`       INT UNSIGNED NOT NULL,
    `requester_id`      INT UNSIGNED NULL,
    `raw_text`          TEXT         NOT NULL,
    `need_category`     ENUM('food','water','medical','rescue') NULL,
    `urgency_score`     DOUBLE       NULL COMMENT '1-10',
    `isolation_weight`  DOUBLE       NULL,
    `severity_weight`   DOUBLE       NULL,
    `household_weight`  DOUBLE       NULL,
    `created_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_relief_requests_incident`  (`incident_id`),
    KEY `idx_relief_requests_requester` (`requester_id`),
    CONSTRAINT `fk_relief_requests_incident`  FOREIGN KEY (`incident_id`)
        REFERENCES `incidents` (`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_relief_requests_requester` FOREIGN KEY (`requester_id`)
        REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- prioritization_scores
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `prioritization_scores` (
    `id`                   INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `relief_request_id`    INT UNSIGNED NOT NULL,
    `composite_score`      DOUBLE       NOT NULL COMMENT '0.0-1.0',
    `isolation_component`  DOUBLE       NOT NULL,
    `severity_component`   DOUBLE       NOT NULL,
    `household_component`  DOUBLE       NOT NULL,
    `need_component`       DOUBLE       NOT NULL,
    `rationale`            TEXT         NULL,
    `computed_at`          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_prioritization_relief_request` (`relief_request_id`),
    CONSTRAINT `fk_prioritization_relief_request` FOREIGN KEY (`relief_request_id`)
        REFERENCES `relief_requests` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- briefings
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `briefings` (
    `id`               INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `generated_by_id`  INT UNSIGNED NULL,
    `snapshot_json`    JSON         NULL,
    `summary_text`     TEXT         NOT NULL,
    `pdf_path`         VARCHAR(512) NULL,
    `created_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_briefings_generated_by` (`generated_by_id`),
    CONSTRAINT `fk_briefings_generated_by` FOREIGN KEY (`generated_by_id`)
        REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- audit_log  (append-only — no UPDATE/DELETE on this table)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `audit_log` (
    `id`           INT UNSIGNED  NOT NULL AUTO_INCREMENT,
    `actor_id`     INT UNSIGNED  NULL,
    `action`       VARCHAR(128)  NOT NULL,
    `entity_type`  VARCHAR(64)   NULL,
    `entity_id`    INT UNSIGNED  NULL,
    `payload`      JSON          NULL,
    `ip_address`   VARCHAR(45)   NULL,
    `created_at`   DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `idx_audit_log_actor`  (`actor_id`),
    KEY `idx_audit_log_action` (`action`),
    CONSTRAINT `fk_audit_log_actor` FOREIGN KEY (`actor_id`)
        REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
