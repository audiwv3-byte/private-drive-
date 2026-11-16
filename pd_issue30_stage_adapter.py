"""Issue #30 offline integration guard — intentionally NOT registered in Flask.

This adapter provides *only* precondition checks. The deployed onboarding is
different from GitHub main. Do not wire this guard until the authoritative
stage-2-submission predicate is matched to actual deployed server code.

Usage within the EXISTING admin SQLite BEGIN IMMEDIATE transaction:
  guard_first_stage(conn, applicant)     # before transition to stage2
  guard_final_stage(conn, applicant, authoritative_stage2_submitted)
                                         # immediately before status='approved'
Neither function commits, grants role, changes files, or changes application.
"""
import pd_document_review as reviews


class IntegrationNotReady(reviews.ReviewError):
    pass


def _assert_review_schema(conn):
    names = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('pd_document_reviews','pd_document_review_events',"
        "'pd_driver_documents','pd_driver_applications')"
    )}
    expected = {'pd_document_reviews', 'pd_document_review_events',
                'pd_driver_documents', 'pd_driver_applications'}
    if names != expected:
        raise IntegrationNotReady("Document review schema has not been migrated")


def _application_status(conn, applicant):
    if type(applicant) is not int or applicant < 1:
        raise reviews.ReviewError("Invalid applicant")
    row = conn.execute(
        "SELECT status FROM pd_driver_applications WHERE telegram_id=?",
        (applicant,),
    ).fetchone()
    if row is None:
        raise reviews.ReviewError("Applicant not found")
    return row[0]


def guard_first_stage(conn, applicant):
    """Precondition for stage1 -> stage2. Call only under existing write lock."""
    _assert_review_schema(conn)
    status = _application_status(conn, applicant)
    if status not in ("pending",):
        raise reviews.ReviewError("Stage-1 transition not allowed")
    reviews.require_approved_documents(conn, applicant, 1)
    return True


def guard_final_stage(conn, applicant, authoritative_stage2_submitted):
    """Precondition for final approval.

    authoritative_stage2_submitted must come from a server-validated persistent
    stage-2 submission, never from JSON supplied by the pilot or dispatcher.
    A missing/unverified predicate is fail-closed.
    """
    _assert_review_schema(conn)
    if authoritative_stage2_submitted is not True:
        raise IntegrationNotReady("Stage-2 submission has not been verified")
    status = _application_status(conn, applicant)
    if status != "pending":
        raise reviews.ReviewError("Final approval not allowed from current state")
    reviews.require_approved_documents(conn, applicant, 2)
    return True
