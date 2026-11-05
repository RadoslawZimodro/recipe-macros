-- Today's calendar date in :tz. The database knows the time zone rules (including summer time),
-- so the application does not need a time zone database of its own.
SELECT CAST(now() AT TIME ZONE :tz AS date) AS day
