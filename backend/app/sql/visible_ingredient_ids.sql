-- Which of the given product ids the current user may reference. A foreign key alone is
-- not enough: FK checks bypass RLS, so a guessed id of someone else's private product
-- would be accepted. Selecting through RLS returns only shared and own products.
SELECT id FROM ingredients WHERE id = ANY(CAST(:ids AS integer[]))
