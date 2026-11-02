-- For each wanted product name: the best product the current user can already see (the shared
-- catalog plus their own; Row-Level Security does the filtering). Names with no match are
-- simply absent from the result.
--   * an exact (case-insensitive) name always wins over a merely similar one;
--   * the user's own product shadows a shared one with the same name;
--   * "similar" means pg_trgm similarity >= :min_similarity, deliberately high, because a wrong
--     link would silently give a recipe wrong macros. The % operator first narrows the
--     candidates with the trigram index ix_ingredients_name_trgm.
--   * numbers in a name carry meaning (2% vs 3,2% milk, flour type 450 vs 550, "00"), and
--     trigrams barely notice them ("mleko 2%" vs "mleko 3,2%" scores exactly 0.80). A similar
--     match is therefore only allowed when both names contain the same digits.
SELECT w.name,
       m.id,
       m.canonical_name,
       m.is_exact
FROM unnest(CAST(:names AS text[])) AS w(name)
CROSS JOIN LATERAL (
    SELECT g.id,
           g.canonical_name,
           lower(g.canonical_name) = lower(w.name) AS is_exact
    FROM ingredients g
    WHERE lower(g.canonical_name) = lower(w.name)
       OR (    g.canonical_name % w.name
           AND similarity(g.canonical_name, w.name) >= :min_similarity
           AND regexp_replace(g.canonical_name, '[^0-9]', '', 'g')
             = regexp_replace(w.name, '[^0-9]', '', 'g'))
    ORDER BY (lower(g.canonical_name) = lower(w.name)) DESC,
             (g.user_id IS NOT NULL) DESC,
             similarity(g.canonical_name, w.name) DESC,
             g.id
    LIMIT 1
) AS m
