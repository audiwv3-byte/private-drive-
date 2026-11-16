"""Issue #30 isolated integration decision bridge — NOT registered or deployed.

Call inside live pd_driver_decide's existing SQLite BEGIN IMMEDIATE transaction,
AFTER server authorization, BEFORE live UPDATE status. Does not commit or write.
The authoritative persisted state is read from SQLite, not from JSON.

Actual live flow observed in GET-only AST:
  stage=1,status='pending', target approved -> stage2 (first gate)
  stage=2,status='pending', target approved -> approved (final gate)
  stage2 upload -> stage=2,status='pending'
"""
import pd_document_review as reviews
from pd_issue30_stage_adapter import guard_first_stage, guard_final_stage


def guard_admin_approval(conn, applicant, requested_target, admin_id, core):
    """Validate live approval. Return effective status; NEVER change DB.

    Caller MUST hold BEGIN IMMEDIATE for entire guard + original UPDATE.
    Authorization cannot be client-supplied; uses the application core.
    For other decisions, preserve existing semantics and do not bypass the
    existing live state validation.
    """
    if type(admin_id) is not int or admin_id <= 0 or not core.is_admin(admin_id):
        raise PermissionError("Dispatcher access required")
    if requested_target not in ("pending", "approved", "rejected"):
        raise reviews.ReviewError("Invalid requested application status")
    if requested_target != "approved":
        return requested_target
    if type(applicant) is not int or applicant <= 0:
        raise reviews.ReviewError("Invalid pilot identifier")
    row = conn.execute(
        "SELECT status, stage FROM pd_driver_applications WHERE telegram_id=?",
        (applicant,),
    ).fetchone()
    if row is None:
        raise reviews.ReviewError("Application not found")
    status, stage = row[0], row[1]
    if status == "approved":
        return "approved"  # existing idempotent decision, do not re-approve files
    if status == "pending" and stage == 1:
        guard_first_stage(conn, applicant)
        return "stage2"
    if status == "pending" and stage == 2:
        # stage=2 alone is NOT enough; require pending + all current exact file SHAs.
        # Evidence comes from persisted state, never from a form or JSON flag.
        guard_final_stage(conn, applicant, authoritative_stage2_submitted=True)
        return "approved"
    raise reviews.ReviewError("Illegal driver approval transition")
