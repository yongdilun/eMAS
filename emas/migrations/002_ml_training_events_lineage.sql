-- ============================================================
-- eMAS Go Backend Migration 002
-- Purpose: promote ml_training_events.lineage_id to the stable primary key.
--
-- Apply after deploying code that writes lineage_id for proposal draft and
-- applied training rows. Take a DB snapshot first. This script uses
-- INFORMATION_SCHEMA checks so it can be reviewed safely against databases
-- that may already have part of the Phase 4 AutoMigrate shape.
-- ============================================================

SET @schema_name := DATABASE();

SET @sql := (
    SELECT IF(COUNT(*) = 0,
        'ALTER TABLE ml_training_events ADD COLUMN lineage_id VARCHAR(80) NULL',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'ml_training_events'
      AND COLUMN_NAME = 'lineage_id'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
    SELECT IF(COUNT(*) = 0,
        'ALTER TABLE ml_training_events ADD COLUMN split_group_id VARCHAR(50) NULL',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'ml_training_events'
      AND COLUMN_NAME = 'split_group_id'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
    SELECT IF(COUNT(*) = 0,
        'ALTER TABLE ml_training_events ADD COLUMN batch_sequence BIGINT DEFAULT 0',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'ml_training_events'
      AND COLUMN_NAME = 'batch_sequence'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

UPDATE ml_training_events
SET lineage_id = slot_id
WHERE (lineage_id IS NULL OR lineage_id = '')
  AND slot_id IS NOT NULL
  AND slot_id <> '';

ALTER TABLE ml_training_events
    MODIFY COLUMN slot_id VARCHAR(50) NULL;

SET @primary_cols := (
    SELECT GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION SEPARATOR ',')
    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'ml_training_events'
      AND CONSTRAINT_NAME = 'PRIMARY'
);

SET @sql := IF(
    @primary_cols = 'lineage_id',
    'SELECT 1',
    IF(
        @primary_cols IS NULL,
        'ALTER TABLE ml_training_events ADD PRIMARY KEY (lineage_id)',
        'ALTER TABLE ml_training_events DROP PRIMARY KEY, ADD PRIMARY KEY (lineage_id)'
    )
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
    SELECT IF(COUNT(*) = 0,
        'CREATE INDEX idx_ml_training_events_slot_id ON ml_training_events(slot_id)',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'ml_training_events'
      AND INDEX_NAME = 'idx_ml_training_events_slot_id'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @sql := (
    SELECT IF(COUNT(*) = 0,
        'CREATE INDEX idx_ml_training_events_split_group_id ON ml_training_events(split_group_id)',
        'SELECT 1'
    )
    FROM INFORMATION_SCHEMA.STATISTICS
    WHERE TABLE_SCHEMA = @schema_name
      AND TABLE_NAME = 'ml_training_events'
      AND INDEX_NAME = 'idx_ml_training_events_split_group_id'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Rollback sketch:
-- 1. Confirm every row has a non-empty slot_id, or choose an archive strategy
--    for draft rows that intentionally do not have a slot_id yet.
-- 2. DROP PRIMARY KEY.
-- 3. ALTER TABLE ml_training_events MODIFY COLUMN slot_id VARCHAR(50) NOT NULL.
-- 4. ALTER TABLE ml_training_events ADD PRIMARY KEY (slot_id).
-- 5. DROP INDEX idx_ml_training_events_slot_id ON ml_training_events.
-- 6. Keep lineage_id/split_group_id/batch_sequence columns until code rollback
--    is complete, then drop them in a separate reviewed migration if needed.

