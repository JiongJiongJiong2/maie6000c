-- Named parameters identify the captured browser request and job.
-- request
SELECT * FROM search_requests WHERE id = :request_id;

-- job
SELECT * FROM search_jobs WHERE id = :job_id;

-- candidates
SELECT * FROM candidates WHERE job_id = :job_id ORDER BY rank;

-- reviews
SELECT * FROM review_decisions WHERE job_id = :job_id ORDER BY created_at;
