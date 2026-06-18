from rest_framework import serializers
from .models import (
    WaxSample, BurnTest, WickProblemAlert, RetestClosure,
    StatusChoices, SmokeLevelChoices, ClosureActionChoices
)


class StatusSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class SmokeLevelSerializer(serializers.Serializer):
    value = serializers.IntegerField()
    label = serializers.CharField()


class BurnTestSerializer(serializers.ModelSerializer):
    burn_duration_minutes = serializers.FloatField(read_only=True)
    wax_sample_display = serializers.CharField(source='wax_sample.__str__', read_only=True)
    smoke_level_display = serializers.CharField(source='get_smoke_level_display', read_only=True)

    class Meta:
        model = BurnTest
        fields = '__all__'
        read_only_fields = ('auto_flags', 'test_time')

    def validate(self, attrs):
        instance = self.instance
        ignite = attrs.get('ignite_time', getattr(instance, 'ignite_time', None) if instance else None)
        extinguish = attrs.get('extinguish_time', getattr(instance, 'extinguish_time', None) if instance else None)
        if ignite and extinguish and extinguish < ignite:
            raise serializers.ValidationError({
                'extinguish_time': '熄灭时间不能早于点燃时间，时长不可为负。'
            })
        return attrs

    def create(self, validated_data):
        instance = super().create(validated_data)
        wax_sample = instance.wax_sample
        if wax_sample.status in [StatusChoices.PENDING_TEST, StatusChoices.PENDING_RETEST]:
            wax_sample.status = StatusChoices.IN_TEST
            wax_sample.save(update_fields=['status', 'updated_at'])
        return instance


class BurnTestListSerializer(serializers.ModelSerializer):
    burn_duration_minutes = serializers.FloatField(read_only=True)
    smoke_level_display = serializers.CharField(source='get_smoke_level_display', read_only=True)

    class Meta:
        model = BurnTest
        fields = [
            'id', 'test_round', 'is_retest', 'ignite_time', 'extinguish_time',
            'melt_pool_diameter', 'smoke_level', 'smoke_level_display',
            'cup_wall_temp', 'burn_duration_minutes', 'auto_flags', 'test_time'
        ]


class WaxSampleSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    latest_test = BurnTestListSerializer(read_only=True)
    retest_count = serializers.IntegerField(read_only=True)
    burn_tests_count = serializers.IntegerField(source='burn_tests.count', read_only=True)

    class Meta:
        model = WaxSample
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def validate(self, attrs):
        if self.instance is None:
            test_batch = attrs.get('test_batch')
            sample_code = attrs.get('sample_code')
            if test_batch and sample_code:
                exists = WaxSample.objects.filter(
                    test_batch=test_batch, sample_code=sample_code
                ).exists()
                if exists:
                    raise serializers.ValidationError({
                        'sample_code': f'测试批次 "{test_batch}" 内蜡样编号 "{sample_code}" 已存在。'
                    })
        return attrs


class WaxSampleDetailSerializer(WaxSampleSerializer):
    burn_tests = BurnTestListSerializer(many=True, read_only=True)


class ProblemWickSerializer(serializers.Serializer):
    wick_spec = serializers.CharField()
    problem_count = serializers.IntegerField()
    total_samples = serializers.IntegerField()
    affected_samples = serializers.ListField(child=serializers.DictField())
    problem_rate = serializers.FloatField()


class PendingRetestSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sample_code = serializers.CharField()
    cup_type = serializers.CharField()
    fragrance_code = serializers.CharField()
    wick_spec = serializers.CharField()
    test_batch = serializers.CharField()
    responsible_person = serializers.CharField()
    status_display = serializers.CharField()
    abnormal_count = serializers.IntegerField()
    last_test_time = serializers.DateTimeField(allow_null=True)
    latest_suggestion = serializers.CharField(allow_null=True)
    retest_overdue = serializers.BooleanField()


class DurationDistributionSerializer(serializers.Serializer):
    range_label = serializers.CharField()
    range_min = serializers.IntegerField()
    range_max = serializers.IntegerField(allow_null=True)
    count = serializers.IntegerField()
    percentage = serializers.FloatField()


class WickProblemAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = WickProblemAlert
        fields = '__all__'
        read_only_fields = ('created_at', 'last_triggered')


class ClosureActionSerializer(serializers.Serializer):
    value = serializers.CharField()
    label = serializers.CharField()


class RetestClosureSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    wax_sample_display = serializers.CharField(source='wax_sample.__str__', read_only=True)

    class Meta:
        model = RetestClosure
        fields = '__all__'
        read_only_fields = ('created_at',)


class ClosureLatestTestSerializer(serializers.ModelSerializer):
    smoke_level_display = serializers.CharField(source='get_smoke_level_display', read_only=True)
    burn_duration_minutes = serializers.FloatField(read_only=True)
    auto_warnings = serializers.ListField(source='analyze_flags.warnings', read_only=True)

    class Meta:
        model = BurnTest
        fields = [
            'id', 'test_round', 'is_retest', 'ignite_time', 'extinguish_time',
            'melt_pool_diameter', 'smoke_level', 'smoke_level_display',
            'cup_wall_temp', 'burn_duration_minutes', 'abnormal_desc',
            'retest_suggestion', 'enter_next_round', 'test_time', 'tested_by',
            'auto_flags', 'auto_warnings'
        ]


class ClosureWickAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = WickProblemAlert
        fields = [
            'id', 'wick_spec', 'test_batch', 'problem_count',
            'affected_samples', 'last_triggered', 'resolved', 'note'
        ]


class ClosureSampleListSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sample_code = serializers.CharField()
    test_batch = serializers.CharField()
    fragrance_code = serializers.CharField()
    cup_type = serializers.CharField()
    wick_spec = serializers.CharField()
    responsible_person = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    abnormal_count = serializers.IntegerField()
    last_test_time = serializers.DateTimeField(allow_null=True)
    latest_suggestion = serializers.CharField(allow_null=True)
    retest_overdue = serializers.BooleanField()
    has_wick_alert = serializers.BooleanField()
    retest_count = serializers.IntegerField()


class ClosureSampleDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    sample_code = serializers.CharField()
    test_batch = serializers.CharField()
    fragrance_code = serializers.CharField()
    cup_type = serializers.CharField()
    wick_spec = serializers.CharField()
    responsible_person = serializers.CharField()
    status = serializers.CharField()
    status_display = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    remarks = serializers.CharField()
    latest_test = ClosureLatestTestSerializer(allow_null=True)
    wick_alerts = ClosureWickAlertSerializer(many=True)
    closure_history = RetestClosureSerializer(many=True)
    retest_overdue = serializers.BooleanField()
    abnormal_count = serializers.IntegerField()


class AbnormalTrendItemSerializer(serializers.Serializer):
    date = serializers.DateField()
    abnormal_count = serializers.IntegerField()
    smoke_high_count = serializers.IntegerField()
    temp_high_count = serializers.IntegerField()
    retest_count = serializers.IntegerField()


class ClosureSummarySerializer(serializers.Serializer):
    pending_retest_count = serializers.IntegerField()
    overdue_retest_count = serializers.IntegerField()
    need_reform_count = serializers.IntegerField()
    unresolved_wick_alerts = serializers.IntegerField()
    abnormal_alerts_count = serializers.IntegerField()
    recent_abnormal_trend = AbnormalTrendItemSerializer(many=True)
    by_batch_top5 = serializers.ListField(child=serializers.DictField())
    by_wick_top5 = serializers.ListField(child=serializers.DictField())


class ClosureHandleSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=ClosureActionChoices.choices)
    handler = serializers.CharField(required=False, allow_blank=True, default='')
    remark = serializers.CharField(required=False, allow_blank=True, default='')
    burn_test_id = serializers.IntegerField(required=False, allow_null=True, default=None)
