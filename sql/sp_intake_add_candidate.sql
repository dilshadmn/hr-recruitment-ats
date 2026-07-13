-- =============================================================================
-- sp_intake_add_candidate
-- Called by the Careers-intake Logic App (replaces the old "Add row to Excel"
-- step). Inserts one candidate into the ATS exactly the way the web app does:
--   * generates a unique candidate_code (CAND-XXXXXXXXXX)
--   * resolves the vacancy from the role text (falls back to General Application)
--   * flags duplicates (email already seen) and blacklisted emails
--   * upserts the email registry
--   * writes the initial "Applied" status-history row (status = OPEN)
-- The new candidate appears in the Open Applications tab.
--
-- Re-runnable: drops and recreates the procedure.
-- =============================================================================
IF OBJECT_ID('dbo.sp_intake_add_candidate', 'P') IS NOT NULL
    DROP PROCEDURE dbo.sp_intake_add_candidate;
GO
CREATE PROCEDURE dbo.sp_intake_add_candidate
    @full_name    nvarchar(255),
    @email        nvarchar(254),
    @phone        nvarchar(20)   = NULL,
    @role_applied nvarchar(255)  = NULL,
    @education    nvarchar(255)  = NULL,
    @cv_link      nvarchar(1000) = NULL,
    @source       nvarchar(255)  = NULL,
    @mail_date    date           = NULL,
    @cv_summary   nvarchar(max)  = NULL
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @email_norm nvarchar(254) = LOWER(LTRIM(RTRIM(@email)));
    DECLARE @now datetimeoffset(7) = SYSDATETIMEOFFSET();
    DECLARE @created datetimeoffset(7) =
        CASE WHEN @mail_date IS NULL THEN @now
             ELSE TODATETIMEOFFSET(CAST(@mail_date AS datetime2), DATEPART(TZOFFSET, @now)) END;

    -- Resolve vacancy: exact title match, else General Application, else NULL
    DECLARE @job_id bigint = (SELECT TOP 1 id FROM dbo.jobs_job
        WHERE LOWER(title) = LOWER(LTRIM(RTRIM(@role_applied))) ORDER BY id);
    IF @job_id IS NULL
        SET @job_id = (SELECT TOP 1 id FROM dbo.jobs_job WHERE title = 'General Application' ORDER BY id);

    -- Duplicate + blacklist detection
    DECLARE @is_dup bit = CASE WHEN EXISTS (
        SELECT 1 FROM dbo.candidates_emailregistry WHERE LOWER(email) = @email_norm) THEN 1 ELSE 0 END;
    DECLARE @is_black bit = CASE WHEN EXISTS (
        SELECT 1 FROM dbo.candidates_blacklist b
        JOIN dbo.candidates_candidate c ON c.id = b.candidate_id
        WHERE LOWER(c.email) = @email_norm) THEN 1 ELSE 0 END;
    DECLARE @status nvarchar(30) = CASE WHEN @is_black = 1 THEN 'BLACKLISTED' ELSE 'OPEN' END;
    DECLARE @code nvarchar(20) = 'CAND-' + UPPER(LEFT(REPLACE(CONVERT(varchar(36), NEWID()), '-', ''), 10));

    INSERT INTO dbo.candidates_candidate
        (candidate_code, full_name, email, phone, qualification, resume_url,
         source, status, is_duplicate, is_blacklisted, is_on_hold,
         created_at, updated_at, job_id, cv_summary)
    VALUES
        (@code, @full_name, @email_norm, @phone, @education, @cv_link,
         ISNULL(@source, 'Careers'), @status, @is_dup, @is_black, 0,
         @created, @now, @job_id, @cv_summary);
    DECLARE @cid bigint = SCOPE_IDENTITY();

    IF @is_dup = 1
        UPDATE dbo.candidates_emailregistry
        SET application_count = application_count + 1, last_applied_at = @now
        WHERE LOWER(email) = @email_norm;
    ELSE
        INSERT INTO dbo.candidates_emailregistry (email, application_count, last_applied_at, first_candidate_id)
        VALUES (@email_norm, 1, @now, @cid);

    INSERT INTO dbo.candidates_candidatestatushistory
        (old_status, new_status, remarks, changed_at, candidate_id, performed_by)
    VALUES ('', @status, 'Applied via careers intake (Logic App)', @created, @cid, 'Careers Intake');

    SELECT @cid AS candidate_id, @code AS candidate_code, @status AS [status],
           @is_dup AS is_duplicate, @job_id AS job_id;
END
GO
