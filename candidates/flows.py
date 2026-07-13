"""Shared stage-flow filters for the funnel dashboard and the candidate list.

A 'flow' names a derived cohort (e.g. 'r1_cleared'). Using one definition in
both places guarantees the dashboard count and the drill-down list always match.
"""
from candidates.models import Candidate, CommunicationLog, Offer
from interviews.models import Interview

S = Candidate.Status
IV = Interview
OUT = CommunicationLog.Outcome
R1 = IV.RoundType.ROUND1
PASS = IV.Result.PASS_
SCHED = IV.Status.SCHEDULED
CANC = IV.Status.CANCELLED
NON_R1 = [t for t, _ in IV.RoundType.choices if t != R1]


def flow_filter(qs, flow):
    """Return `qs` narrowed to the named flow cohort (distinct)."""
    table = {
        'all': qs,
        'open': qs.filter(status=S.OPEN),
        # Screening
        'unfit': qs.filter(status=S.REJECTED).exclude(history__new_status=S.SHORTLISTED),
        'ever_shortlisted': qs.filter(history__new_status=S.SHORTLISTED),
        # Call
        'call_pending': qs.filter(status=S.SHORTLISTED, communication_logs__isnull=True),
        'shortlisted_after_call': qs.filter(communication_logs__outcome=OUT.SHORTLISTED),
        'unable_to_connect': qs.filter(communication_logs__outcome=OUT.UNABLE),
        # Round 1
        'r1_cleared': qs.filter(interviews__round_type=R1, interviews__result=PASS),
        'r1_scheduled': qs.filter(interviews__round_type=R1, interviews__status=SCHED),
        'r1_no_show': qs.filter(interviews__round_type=R1, interviews__status=CANC),
        'r1_yet': qs.filter(status=S.ROUND1).exclude(interviews__round_type=R1),
        # Round 2 (final interview)
        'r2_cleared': qs.filter(interviews__round_type__in=NON_R1, interviews__result=PASS),
        'r2_scheduled': qs.filter(interviews__round_type__in=NON_R1, interviews__status=SCHED),
        'r2_no_show': qs.filter(interviews__round_type__in=NON_R1, interviews__status=CANC),
        'r2_yet': qs.filter(status=S.INTERVIEW).exclude(interviews__round_type__in=NON_R1),
        # Offer / Hire
        'on_hold': qs.filter(is_on_hold=True),
        'hired': qs.filter(status=S.HIRED),
        'offer_pending': qs.filter(offers__status=Offer.Status.SENT),
        'offer_declined': qs.filter(offers__status=Offer.Status.DECLINED),
        # Terminal
        'rejected': qs.filter(status=S.REJECTED),
        'blacklisted': qs.filter(status=S.BLACKLISTED),
    }
    result = table.get(flow)
    if result is None:
        return qs
    return result.distinct()


def flow_count(qs, flow):
    return flow_filter(qs, flow).count()
