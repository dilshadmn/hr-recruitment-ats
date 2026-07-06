from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

HR_ADMIN = 'HR Admin'
RECRUITER = 'Recruiter'
INTERVIEWER = 'Interviewer'
HIRING_MANAGER = 'Hiring Manager'

ALL_GROUPS = (HR_ADMIN, RECRUITER, INTERVIEWER, HIRING_MANAGER)

# Any authenticated HR-side user (any of the four groups, or a superuser).
ANY_STAFF = ALL_GROUPS


class GroupRequiredMixin(LoginRequiredMixin):
    """Restricts a view to superusers or members of `allowed_groups`.

    Usage: class MyView(GroupRequiredMixin, ...):
               allowed_groups = (permissions.HR_ADMIN, permissions.RECRUITER)
    """
    allowed_groups = ANY_STAFF

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (request.user.is_superuser or request.user.groups.filter(name__in=self.allowed_groups).exists()):
            raise PermissionDenied("Your role does not have access to this page.")
        return super().dispatch(request, *args, **kwargs)
