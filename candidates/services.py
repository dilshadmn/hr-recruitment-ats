"""Duplicate/blacklist detection and status-transition helpers for the
candidates app, built around the email_registry + blacklist tables.
"""
from .models import Blacklist, Candidate, CandidateStatusHistory, EmailRegistry

STATUS = Candidate.Status


def check_email(email):
    """Look up an applicant's email before creating a Candidate row.

    Returns (is_duplicate, is_blacklisted):
      - blacklisted: this email has an active Blacklist entry -> new
        application is auto-blacklisted too.
      - duplicate: email already exists in the registry (a "Reapply") but
        is not blacklisted.
      - neither: brand new applicant.
    """
    registry_entry = EmailRegistry.objects.filter(email__iexact=email).first()
    if registry_entry is None:
        return False, False

    is_blacklisted = Blacklist.objects.filter(candidate__email__iexact=email).exists()
    return True, is_blacklisted


def register_application(candidate):
    """Create/update the email_registry row for this candidate's email."""
    entry = EmailRegistry.objects.filter(email__iexact=candidate.email).first()
    if entry is None:
        return EmailRegistry.objects.create(
            email=candidate.email, first_candidate=candidate, application_count=1
        )
    entry.application_count = entry.application_count + 1
    entry.save(update_fields=['application_count', 'last_applied_at'])
    return entry


def record_creation(candidate, user=None, remarks=None):
    CandidateStatusHistory.objects.create(
        candidate=candidate, old_status='', new_status=candidate.status,
        changed_by=user, remarks=remarks,
    )


def change_status(candidate, new_status, user=None, remarks=None):
    old_status = candidate.status
    if old_status == new_status:
        return candidate
    candidate.status = new_status
    candidate.save(update_fields=['status', 'updated_at'])
    CandidateStatusHistory.objects.create(
        candidate=candidate, old_status=old_status, new_status=new_status,
        changed_by=user, remarks=remarks,
    )
    return candidate


def blacklist_candidate(candidate, reason, user=None):
    Blacklist.objects.create(candidate=candidate, reason=reason, blacklisted_by=user)
    candidate.is_blacklisted = True
    candidate.save(update_fields=['is_blacklisted'])
    change_status(candidate, STATUS.BLACKLISTED, user=user, remarks=reason)
    return candidate


def submit_application(candidate):
    """Run duplicate/blacklist detection, save the candidate, log the
    initial status, and register the email. Called from the public
    application form on submit.
    """
    is_duplicate, is_blacklisted = check_email(candidate.email)
    candidate.is_duplicate = is_duplicate
    candidate.is_blacklisted = is_blacklisted
    candidate.status = STATUS.BLACKLISTED if is_blacklisted else STATUS.OPEN
    candidate.save()
    register_application(candidate)
    record_creation(candidate)
    return candidate
