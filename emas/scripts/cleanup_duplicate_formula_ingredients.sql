-- Clean duplicate formula_ingredients (same formula_id + material_id or formula_id + product_id).
-- Run against your emas database.

-- Option A (recommended): Clear all and re-seed. Simplest, restores clean seed data.
-- Run this, then: go run ./cmd/seed
DELETE FROM formula_ingredients;

-- Option B: Delete duplicates only (keeps one per formula+material or formula+product).
-- Uncomment if you have custom ingredients to preserve. Prefers rows with ingredient_id LIKE 'ING-F%'.
-- Requires MySQL 8+ for ROW_NUMBER.
/*
DELETE fi FROM formula_ingredients fi
WHERE (formula_id, ingredient_id) NOT IN (
  SELECT formula_id, keeper FROM (
    SELECT formula_id,
      COALESCE(
        MAX(CASE WHEN ingredient_id LIKE 'ING-F%%' THEN ingredient_id END),
        MIN(ingredient_id)
      ) AS keeper
    FROM formula_ingredients
    GROUP BY formula_id, COALESCE(material_id,''), COALESCE(product_id,'')
  ) x
);
*/
