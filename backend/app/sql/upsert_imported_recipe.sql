-- Insert an imported recipe or, if the user already has an active recipe from the same
-- address, overwrite its imported content. The conflict target is the partial unique index
-- uq_recipes_user_source_url, so its predicate must be repeated here.
--
-- RETURNING reports what happened: in an ON CONFLICT ... DO UPDATE the old row version is
-- replaced, so a non-zero xmax means "this row was updated", zero means "freshly inserted".
-- created_at and the id stay; updated_at is bumped by the trg_recipes_set_updated_at trigger.
INSERT INTO recipes (
    user_id, title, description, source_url, servings, image_url,
    prep_time_min, cook_time_min, tags, source_nutrition, import_method, imported_at
)
VALUES (
    :user_id, :title, :description, :source_url, :servings, :image_url,
    :prep_time_min, :cook_time_min, CAST(:tags AS text[]),
    CAST(:source_nutrition AS jsonb), :import_method, now()
)
ON CONFLICT (user_id, source_url) WHERE source_url IS NOT NULL AND deleted_at IS NULL
DO UPDATE SET
    title            = EXCLUDED.title,
    description      = EXCLUDED.description,
    servings         = EXCLUDED.servings,
    image_url        = EXCLUDED.image_url,
    prep_time_min    = EXCLUDED.prep_time_min,
    cook_time_min    = EXCLUDED.cook_time_min,
    tags             = EXCLUDED.tags,
    source_nutrition = EXCLUDED.source_nutrition,
    import_method    = EXCLUDED.import_method,
    imported_at      = EXCLUDED.imported_at
RETURNING id, (xmax = 0) AS inserted
