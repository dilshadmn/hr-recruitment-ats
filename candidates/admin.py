from django.contrib import admin

from .models import (
    Attachment,
    Blacklist,
    Candidate,
    CandidateEducation,
    CandidateExperience,
    CandidateStatusHistory,
    CommunicationLog,
    EmailRegistry,
    Note,
    Offer,
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


class NoteInline(admin.TabularInline):
    model = Note
    extra = 0


class CommunicationLogInline(admin.TabularInline):
    model = CommunicationLog
    extra = 0


class OfferInline(admin.TabularInline):
    model = Offer
    extra = 0


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        'candidate_code', 'full_name', 'email', 'phone', 'job', 'status',
        'is_duplicate', 'is_blacklisted', 'created_at',
    )
    list_filter = ('status', 'job', 'is_duplicate', 'is_blacklisted', 'source')
    search_fields = ('candidate_code', 'full_name', 'email', 'phone')
    readonly_fields = ('candidate_code', 'created_at', 'updated_at')
    inlines = [
        CandidateEducationInline, CandidateExperienceInline, CandidateStatusHistoryInline,
        NoteInline, CommunicationLogInline, OfferInline,
    ]


@admin.register(Blacklist)
class BlacklistAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'reason', 'blacklisted_by', 'blacklisted_at')
    search_fields = ('candidate__full_name', 'candidate__email')


@admin.register(EmailRegistry)
class EmailRegistryAdmin(admin.ModelAdmin):
    list_display = ('email', 'first_candidate', 'application_count', 'last_applied_at')
    search_fields = ('email',)


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'label', 'uploaded_by', 'uploaded_at')


@admin.register(Offer)
class OfferAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'status', 'sent_at', 'created_by', 'created_at')
    list_filter = ('status',)
