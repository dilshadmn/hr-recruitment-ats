from django.contrib import admin

from .models import (
    Blacklist,
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidateStatusHistory,
    EmailRegistry,
)


class CandidateEducationInline(admin.TabularInline):
    model = CandidateEducation
    extra = 0


class CandidateExperienceInline(admin.TabularInline):
    model = CandidateExperience
    extra = 0


class CandidateStatusHistoryInline(admin.TabularInline):
    model = CandidateStatusHistory
    extra = 0
    readonly_fields = ('old_status', 'new_status', 'changed_by', 'remarks', 'changed_at')
    can_delete = False


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        'candidate_code', 'full_name', 'email', 'phone', 'job', 'status',
        'is_duplicate', 'is_blacklisted', 'created_at',
    )
    list_filter = ('status', 'job', 'is_duplicate', 'is_blacklisted', 'source')
    search_fields = ('candidate_code', 'full_name', 'email', 'phone')
    readonly_fields = ('candidate_code', 'created_at', 'updated_at')
    inlines = [CandidateEducationInline, CandidateExperienceInline, CandidateStatusHistoryInline]


@admin.register(Blacklist)
class BlacklistAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'reason', 'blacklisted_by', 'blacklisted_at')
    search_fields = ('candidate__full_name', 'candidate__email')


@admin.register(EmailRegistry)
class EmailRegistryAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_candidate', 'application_count', 'last_applied_at')
    search_fields = ('email',)
