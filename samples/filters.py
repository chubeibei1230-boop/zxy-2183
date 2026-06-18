from django.db.models import Q
from django_filters import rest_framework as filters
from .models import WaxSample, BurnTest, StatusChoices, SmokeLevelChoices


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
