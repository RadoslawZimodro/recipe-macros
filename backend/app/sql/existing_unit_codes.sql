-- Which of the given unit codes exist (validates recipe lines before writing them).
SELECT code FROM units WHERE code = ANY(CAST(:codes AS text[]))
