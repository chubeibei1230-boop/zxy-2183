from django.db.models import Q
from django_filters import rest_framework as filters
from .models import WaxSample, BurnTest, RetestClosure, WickProblemAlert, RetestPlan, RetestPlanExecution, StatusChoices, SmokeLevelChoices, ClosureActionChoices, PlanStatusChoices, PlanSourceChoices


class WaxSampleFilter(filters.FilterSet):
    fragrance_code = filters.CharFilter(field_name='fragrance_code', lookup_expr='icontains')
    cup_type = filters.CharFilter(field_name='cup_type', lookup_expr='icontains')
    wick_spec = filters.CharFilter(field_name='wick_spec', lookup_expr='icontains')
    test_batch = filters.CharFilter(field_name='test_batch', lookup_expr='icontains')
    status = filters.ChoiceFilter(choices=StatusChoices.choices)
    responsible_person = filters.CharFilter(field_name='responsible_person', lookup_expr='icontains')
    sample_code = filters.CharFilter(field_name='sample_code', lookup_expr='icontains')
    created_from = filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    created_to = filters.DateFilter(field_name='created_at', lookup_expr='date__lte')
    updated_from = filters.DateFilter(field_name='updated_at', lookup_expr='date__gte')
    updated_to = filters.DateFilter(field_name='updated_at', lookup_expr='date__lte')

    has_abnormal = filters.BooleanFilter(method='filter_has_abnormal')
    smoke_level = filters.ChoiceFilter(
        method='filter_smoke_level',
        choices=SmokeLevelChoices.choices
    )
    smoke_level_ge = filters.ChoiceFilter(
        method='filter_smoke_level_ge',
        choices=SmokeLevelChoices.choices,
        label='烟量等级大于等于'
    )

    class Meta:
        model = WaxSample
        fields = []

    def filter_has_abnormal(self, queryset, name, value):
        if value:
            return queryset.filter(
                burn_tests__isnull=False,
                burn_tests__abnormal_desc__gt=''
            ).distinct()
        return queryset

    def filter_smoke_level(self, queryset, name, value):
        if value:
            return queryset.filter(
                burn_tests__smoke_level=int(value)
            ).distinct()
        return queryset

    def filter_smoke_level_ge(self, queryset, name, value):
        if value:
            return queryset.filter(
                burn_tests__smoke_level__gte=int(value)
            ).distinct()
        return queryset


class BurnTestFilter(filters.FilterSet):
    fragrance_code = filters.CharFilter(field_name='wax_sample__fragrance_code', lookup_expr='icontains')
    cup_type = filters.CharFilter(field_name='wax_sample__cup_type', lookup_expr='icontains')
    wick_spec = filters.CharFilter(field_name='wax_sample__wick_spec', lookup_expr='icontains')
    test_batch = filters.CharFilter(field_name='wax_sample__test_batch', lookup_expr='icontains')
    sample_code = filters.CharFilter(field_name='wax_sample__sample_code', lookup_expr='icontains')
    smoke_level = filters.ChoiceFilter(choices=SmokeLevelChoices.choices)
    smoke_level_ge = filters.NumberFilter(field_name='smoke_level', lookup_expr='gte')
    is_retest = filters.BooleanFilter()
    test_round = filters.NumberFilter()
    test_from = filters.DateFilter(field_name='test_time', lookup_expr='date__gte')
    test_to = filters.DateFilter(field_name='test_time', lookup_expr='date__lte')
    has_abnormal = filters.BooleanFilter(method='filter_has_abnormal')
    temp_high = filters.BooleanFilter(method='filter_temp_high')
    smoke_high = filters.BooleanFilter(method='filter_smoke_high')

    class Meta:
        model = BurnTest
        fields = ['wax_sample']

    def filter_has_abnormal(self, queryset, name, value):
        if value:
            return queryset.filter(abnormal_desc__gt='')
        return queryset

    def filter_temp_high(self, queryset, name, value):
        if value:
            return queryset.filter(auto_flags__temp_high=True)
        return queryset

    def filter_smoke_high(self, queryset, name, value):
        if value:
            return queryset.filter(auto_flags__smoke_high=True)
        return queryset


class ClosureSampleFilter(filters.FilterSet):
    test_batch = filters.CharFilter(field_name='test_batch', lookup_expr='icontains')
    fragrance_code = filters.CharFilter(field_name='fragrance_code', lookup_expr='icontains')
    cup_type = filters.CharFilter(field_name='cup_type', lookup_expr='icontains')
    wick_spec = filters.CharFilter(field_name='wick_spec', lookup_expr='icontains')
    responsible_person = filters.CharFilter(field_name='responsible_person', lookup_expr='icontains')
    status = filters.ChoiceFilter(choices=StatusChoices.choices)
    retest_overdue = filters.BooleanFilter(method='filter_retest_overdue')
    has_wick_alert = filters.BooleanFilter(method='filter_has_wick_alert')
    has_abnormal = filters.BooleanFilter(method='filter_has_abnormal')

    class Meta:
        model = WaxSample
        fields = []

    def filter_retest_overdue(self, queryset, name, value):
        from django.utils import timezone
        from datetime import timedelta
        from .models import RETARGET_MISSING_DAYS
        ids = []
        for s in queryset.filter(status=StatusChoices.PENDING_RETEST).prefetch_related('burn_tests'):
            latest = s.burn_tests.order_by('-test_time').first()
            is_overdue = False
            if not latest:
                is_overdue = True
            elif not latest.is_retest:
                cutoff = latest.test_time + timedelta(days=RETARGET_MISSING_DAYS)
                is_overdue = timezone.now() > cutoff
            if is_overdue == value:
                ids.append(s.id)
        return queryset.filter(id__in=ids)

    def filter_has_wick_alert(self, queryset, name, value):
        if value:
            return queryset.filter(
                Q(test_batch__in=list(
                    WickProblemAlert.objects.filter(resolved=False).values_list('test_batch', flat=True)
                )) & Q(wick_spec__in=list(
                    WickProblemAlert.objects.filter(resolved=False).values_list('wick_spec', flat=True)
                ))
            ).distinct()
        return queryset

    def filter_has_abnormal(self, queryset, name, value):
        if value:
            return queryset.filter(
                burn_tests__isnull=False
            ).filter(
                Q(burn_tests__abnormal_desc__gt='')
                | Q(burn_tests__auto_flags__smoke_high=True)
                | Q(burn_tests__auto_flags__temp_high=True)
            ).distinct()
        return queryset


class RetestClosureFilter(filters.FilterSet):
    test_batch = filters.CharFilter(field_name='wax_sample__test_batch', lookup_expr='icontains')
    sample_code = filters.CharFilter(field_name='wax_sample__sample_code', lookup_expr='icontains')
    wick_spec = filters.CharFilter(field_name='wax_sample__wick_spec', lookup_expr='icontains')
    action = filters.ChoiceFilter(choices=ClosureActionChoices.choices)
    handler = filters.CharFilter(field_name='handler', lookup_expr='icontains')
    created_from = filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    created_to = filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = RetestClosure
        fields = ['wax_sample']


class RetestPlanFilter(filters.FilterSet):
    test_batch = filters.CharFilter(field_name='wax_sample__test_batch', lookup_expr='icontains')
    sample_code = filters.CharFilter(field_name='wax_sample__sample_code', lookup_expr='icontains')
    fragrance_code = filters.CharFilter(field_name='wax_sample__fragrance_code', lookup_expr='icontains')
    cup_type = filters.CharFilter(field_name='wax_sample__cup_type', lookup_expr='icontains')
    wick_spec = filters.CharFilter(field_name='wax_sample__wick_spec', lookup_expr='icontains')
    responsible_person = filters.CharFilter(field_name='responsible_person', lookup_expr='icontains')
    plan_status = filters.ChoiceFilter(choices=PlanStatusChoices.choices)
    source_reason = filters.ChoiceFilter(choices=PlanSourceChoices.choices)
    is_overdue = filters.BooleanFilter(method='filter_is_overdue')
    planned_from = filters.DateTimeFilter(field_name='planned_retest_time', lookup_expr='gte')
    planned_to = filters.DateTimeFilter(field_name='planned_retest_time', lookup_expr='lte')
    created_from = filters.DateFilter(field_name='created_at', lookup_expr='date__gte')
    created_to = filters.DateFilter(field_name='created_at', lookup_expr='date__lte')

    class Meta:
        model = RetestPlan
        fields = ['wax_sample']

    def filter_is_overdue(self, queryset, name, value):
        from django.utils import timezone
        now = timezone.now()
        ids = []
        for plan in queryset:
            if plan.plan_status in [PlanStatusChoices.COMPLETED, PlanStatusChoices.CANCELLED]:
                is_overdue = False
            else:
                is_overdue = now > plan.planned_retest_time
            if is_overdue == value:
                ids.append(plan.id)
        return queryset.filter(id__in=ids)


class RetestPlanExecutionFilter(filters.FilterSet):
    test_batch = filters.CharFilter(field_name='retest_plan__wax_sample__test_batch', lookup_expr='icontains')
    sample_code = filters.CharFilter(field_name='retest_plan__wax_sample__sample_code', lookup_expr='icontains')
    plan_no = filters.CharFilter(field_name='retest_plan__plan_no', lookup_expr='icontains')
    executed_by = filters.CharFilter(field_name='executed_by', lookup_expr='icontains')
    closure_action = filters.ChoiceFilter(choices=ClosureActionChoices.choices)
    actual_from = filters.DateTimeFilter(field_name='actual_retest_time', lookup_expr='gte')
    actual_to = filters.DateTimeFilter(field_name='actual_retest_time', lookup_expr='lte')

    class Meta:
        model = RetestPlanExecution
        fields = ['retest_plan']
