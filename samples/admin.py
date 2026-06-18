from django.contrib import admin
from .models import WaxSample, BurnTest, WickProblemAlert, RetestClosure


class BurnTestInline(admin.TabularInline):
    model = BurnTest
    extra = 0
    fields = [
        'test_round', 'is_retest', 'ignite_time', 'extinguish_time',
        'melt_pool_diameter', 'smoke_level', 'cup_wall_temp',
        'enter_next_round', 'tested_by'
    ]
    readonly_fields = ['auto_flags', 'test_time']


class RetestClosureInline(admin.TabularInline):
    model = RetestClosure
    extra = 0
    fields = ['action', 'handler', 'remark', 'created_at']
    readonly_fields = ['created_at']


@admin.register(WaxSample)
class WaxSampleAdmin(admin.ModelAdmin):
    list_display = [
        'sample_code', 'test_batch', 'cup_type', 'fragrance_code',
        'wick_spec', 'responsible_person', 'status', 'created_at'
    ]
    list_filter = ['status', 'cup_type', 'test_batch', 'wick_spec']
    search_fields = [
        'sample_code', 'test_batch', 'fragrance_code',
        'wick_spec', 'responsible_person'
    ]
    inlines = [BurnTestInline, RetestClosureInline]
    readonly_fields = ['created_at', 'updated_at']


@admin.register(BurnTest)
class BurnTestAdmin(admin.ModelAdmin):
    list_display = [
        'wax_sample', 'test_round', 'is_retest', 'ignite_time',
        'smoke_level', 'cup_wall_temp', 'burn_duration_minutes',
        'enter_next_round', 'tested_by'
    ]
    list_filter = ['is_retest', 'smoke_level', 'enter_next_round']
    search_fields = [
        'wax_sample__sample_code', 'wax_sample__test_batch',
        'tested_by', 'abnormal_desc', 'retest_suggestion'
    ]
    readonly_fields = ['auto_flags', 'test_time', 'burn_duration_minutes']


@admin.register(WickProblemAlert)
class WickProblemAlertAdmin(admin.ModelAdmin):
    list_display = [
        'wick_spec', 'test_batch', 'problem_count',
        'resolved', 'last_triggered'
    ]
    list_filter = ['resolved', 'test_batch', 'wick_spec']
    search_fields = ['wick_spec', 'test_batch', 'note']
    readonly_fields = ['created_at', 'last_triggered']


@admin.register(RetestClosure)
class RetestClosureAdmin(admin.ModelAdmin):
    list_display = [
        'wax_sample', 'action', 'handler', 'burn_test', 'created_at'
    ]
    list_filter = ['action', 'created_at']
    search_fields = [
        'wax_sample__sample_code', 'wax_sample__test_batch',
        'handler', 'remark'
    ]
    readonly_fields = ['created_at']
