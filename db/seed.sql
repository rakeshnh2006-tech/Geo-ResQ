-- =============================================================================
-- seed.sql  —  Development seed data for Malenadu Resilience Impact Agent
-- Run AFTER 001_initial.sql
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------------
-- Users: 1 coordinator + 2 citizens
-- Passwords are bcrypt hashes of "Password1!"
-- ---------------------------------------------------------------------------
INSERT INTO `users` (`email`, `password_hash`, `full_name`, `role`, `is_active`) VALUES
('coordinator@georesq.dev',
 '$2b$12$AAAAAAAAAAAAAAAAAAAAAO0YQQ7PVL.FvgIVSZkiYQKdSgOr4.QH6',
 'Priya Coordinator', 'coordinator', 1),
('citizen1@georesq.dev',
 '$2b$12$AAAAAAAAAAAAAAAAAAAAAO0YQQ7PVL.FvgIVSZkiYQKdSgOr4.QH6',
 'Ravi Citizen', 'citizen', 1),
('citizen2@georesq.dev',
 '$2b$12$AAAAAAAAAAAAAAAAAAAAAO0YQQ7PVL.FvgIVSZkiYQKdSgOr4.QH6',
 'Meena Citizen', 'citizen', 1)
ON DUPLICATE KEY UPDATE `full_name` = VALUES(`full_name`);

-- ---------------------------------------------------------------------------
-- Villages  (Malenadu bounding box: 13.0–14.5°N, 75.0–76.0°E)
-- ---------------------------------------------------------------------------
INSERT INTO `villages`
    (`osm_node_id`, `name`, `lat`, `lng`, `population`, `is_town`)
VALUES
    (1001, 'Shimoga',    14.0027, 75.5681, 274000, 1),
    (1002, 'Chikmagalur',13.3153, 75.7754,  60000, 1),
    (1003, 'Sringeri',   13.4178, 75.2543,   8000, 1),
    (1004, 'Kalasa',     13.3419, 75.3611,   3500, 0),
    (1005, 'Hornadu',    13.3876, 75.1951,   1200, 0),
    (1006, 'Balehonnur', 13.1753, 75.5081,   2200, 0),
    (1007, 'Mudigere',   13.1308, 75.6494,   4000, 0),
    (1008, 'Kottigehara',13.2528, 75.4658,    800, 0)
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`), `population` = VALUES(`population`);

-- ---------------------------------------------------------------------------
-- Road segments  (synthetic edges connecting the villages above)
-- ---------------------------------------------------------------------------
INSERT INTO `road_segments`
    (`osm_way_id`, `name`, `highway_type`,
     `start_node_id`, `end_node_id`,
     `start_lat`, `start_lng`, `end_lat`, `end_lng`, `length_m`, `blocked`)
VALUES
    (2001, 'NH-173 (Shimoga–Chikmagalur)', 'primary',
     1001, 1002, 14.0027, 75.5681, 13.3153, 75.7754, 90000, 0),
    (2002, 'SH-57 (Chikmagalur–Sringeri)', 'secondary',
     1002, 1003, 13.3153, 75.7754, 13.4178, 75.2543, 55000, 0),
    (2003, 'MDR (Sringeri–Kalasa)',         'tertiary',
     1003, 1004, 13.4178, 75.2543, 13.3419, 75.3611, 15000, 0),
    (2004, 'MDR (Kalasa–Hornadu)',           'tertiary',
     1004, 1005, 13.3419, 75.3611, 13.3876, 75.1951, 22000, 0),
    (2005, 'MDR (Sringeri–Balehonnur)',      'tertiary',
     1003, 1006, 13.4178, 75.2543, 13.1753, 75.5081, 32000, 0),
    (2006, 'SH (Balehonnur–Mudigere)',       'secondary',
     1006, 1007, 13.1753, 75.5081, 13.1308, 75.6494, 18000, 0),
    (2007, 'MDR (Kalasa–Kottigehara)',        'tertiary',
     1004, 1008, 13.3419, 75.3611, 13.2528, 75.4658, 20000, 0)
ON DUPLICATE KEY UPDATE `blocked` = VALUES(`blocked`);

SET FOREIGN_KEY_CHECKS = 1;
