from rest_framework import serializers
from .models import WaxSample, BurnTest, StatusChoices, SmokeLevelChoices


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
        ignite = attrs.get('ignite_time')
        extinguish = attrs.get('extinguish_time')
        if ignite and extinguish and extinguish < ignite:
            raise serializers.ValidationError('熄灭时间不能早于点燃时间')
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


class DurationDistributionSerializer(serializers.Serializer):
    range_label = serializers.CharField()
    range_min = serializers.IntegerField()
    range_max = serializers.IntegerField(allow_null=True)
    count = serializers.IntegerField()
    percentage = serializers.FloatField()
