from django.contrib import admin

from .models import Candidate, CandidateStatusHistory, Role


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('title', 'department', 'location', 'is_active', 'created_at')
    list_filter = ('is_active', 'department')
    search_fields = ('title', 'department', 'location')


class CandidateStatusHistoryInline(admin.TabularInline):
    model = CandidateStatusHistory
    extra = 0
    readonly_fields = ('old_status', 'new_status', 'changed_by', 'changed_at')
    can_delete = False
    ordering = ('-changed_at',)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = (
        'full_name', 'email', 'phone', 'role', 'current_status',
        'duplicate_flag', 'source', 'applied_at',
    )
    list_filter = ('current_status', 'role', 'duplicate_flag', 'source')
    search_fields = ('full_name', 'email', 'phone')
    date_hierarchy = 'applied_at'
    inlines = [CandidateStatusHistoryInline]
    readonly_fields = ('applied_at', 'updated_at')


@admin.register(CandidateStatusHistory)
class CandidateStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ('candidate', 'old_status', 'new_status', 'changed_by', 'changed_at')
    list_filter = ('new_status',)
    search_fields = ('candidate__full_name', 'candidate__email')
