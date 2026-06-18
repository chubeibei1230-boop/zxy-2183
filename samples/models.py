from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone


class StatusChoices(models.TextChoices):
    PENDING_PROOFING = 'pending_proofing', '待打样'
    PENDING_TEST = 'pending_test', '待测试'
    IN_TEST = 'in_test', '测试中'
    PENDING_RETEST = 'pending_retest', '待复测'
    NEED_REFORM = 'need_reform', '需改配'
    VERSION_READY = 'version_ready', '可归入版本库'


class SmokeLevelChoices(models.IntegerChoices):
    LEVEL_1 = 1, '1级-无烟'
    LEVEL_2 = 2, '2级-轻微'
    LEVEL_3 = 3, '3级-中等'
    LEVEL_4 = 4, '4级-偏高'
    LEVEL_5 = 5, '5级-严重'


SMOKE_HIGH_THRESHOLD = 3
TEMP_HIGH_THRESHOLD = 65.0
TEMP_LOW_THRESHOLD = 30.0
WICK_PROBLEM_THRESHOLD = 3


class WaxSample(models.Model):
    sample_code = models.CharField('蜡样编号', max_length=50)
    cup_type = models.CharField('杯型', max_length=50)
    fragrance_code = models.CharField('香型代号', max_length=50)
    wick_spec = models.CharField('芯线规格', max_length=50)
    test_batch = models.CharField('测试批次', max_length=50)
    responsible_person = models.CharField('责任人', max_length=50)
    status = models.CharField(
        '状态',
        max_length=20,
        choices=StatusChoices.choices,
        default=StatusChoices.PENDING_PROOFING,
    )
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)
    remarks = models.TextField('备注', blank=True, default='')

    class Meta:
        verbose_name = '蜡样'
        verbose_name_plural = '蜡样'
        ordering = ['-created_at']
        unique_together = [['test_batch', 'sample_code']]

    def __str__(self):
        return f'[{self.test_batch}] {self.sample_code}'

    def clean(self):
        super().clean()
        if not self.pk:
            existing = WaxSample.objects.filter(
                test_batch=self.test_batch,
                sample_code=self.sample_code
            ).exists()
            if existing:
                raise ValidationError({
                    'sample_code': f'测试批次 "{self.test_batch}" 内蜡样编号 "{self.sample_code}" 已存在，不可重复。'
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def latest_test(self):
        return self.burn_tests.order_by('-test_time').first()

    @property
    def retest_count(self):
        return self.burn_tests.filter(is_retest=True).count()


class BurnTest(models.Model):
    wax_sample = models.ForeignKey(
        WaxSample,
        on_delete=models.CASCADE,
        related_name='burn_tests',
        verbose_name='蜡样'
    )
    test_round = models.PositiveIntegerField('测试轮次', default=1)
    is_retest = models.BooleanField('是否复测', default=False)
    ignite_time = models.DateTimeField('点燃时间')
    extinguish_time = models.DateTimeField('熄灭时间', null=True, blank=True)
    melt_pool_diameter = models.FloatField('熔池直径(cm)', null=True, blank=True)
    smoke_level = models.IntegerField(
        '烟量等级',
        choices=SmokeLevelChoices.choices,
        null=True,
        blank=True
    )
    cup_wall_temp = models.FloatField('杯壁温度(℃)', null=True, blank=True)
    abnormal_desc = models.TextField('异常描述', blank=True, default='')
    retest_suggestion = models.TextField('复测建议', blank=True, default='')
    enter_next_round = models.BooleanField('是否进入下一轮', null=True, blank=True)
    test_time = models.DateTimeField('记录时间', auto_now_add=True)
    tested_by = models.CharField('测试人', max_length=50, blank=True, default='')

    auto_flags = models.JSONField('自动识别标记', default=dict, blank=True)

    class Meta:
        verbose_name = '燃烧测试记录'
        verbose_name_plural = '燃烧测试记录'
        ordering = ['-test_time']

    def __str__(self):
        return f'{self.wax_sample} - 第{self.test_round}轮'

    @property
    def burn_duration_minutes(self):
        if self.ignite_time and self.extinguish_time:
            delta = self.extinguish_time - self.ignite_time
            return round(delta.total_seconds() / 60, 1)
        return None

    def analyze_flags(self):
        flags = {}
        warnings = []

        if self.smoke_level is not None and self.smoke_level >= SMOKE_HIGH_THRESHOLD:
            flags['smoke_high'] = True
            warnings.append(f'烟量偏高(等级{self.smoke_level})')

        if self.cup_wall_temp is not None:
            if self.cup_wall_temp >= TEMP_HIGH_THRESHOLD:
                flags['temp_high'] = True
                warnings.append(f'杯壁温度偏高({self.cup_wall_temp}℃)')
            elif self.cup_wall_temp <= TEMP_LOW_THRESHOLD:
                flags['temp_low'] = True
                warnings.append(f'杯壁温度偏低({self.cup_wall_temp}℃)')

        if self.is_retest:
            if not self.smoke_level or self.cup_wall_temp is None or self.melt_pool_diameter is None:
                flags['retest_data_missing'] = True
                warnings.append('复测关键数据缺失')

        if self.abnormal_desc and not self.retest_suggestion:
            flags['suggestion_missing'] = True
            warnings.append('存在异常但未填写复测建议')

        flags['warnings'] = warnings
        return flags

    def save(self, *args, **kwargs):
        self.auto_flags = self.analyze_flags()
        super().save(*args, **kwargs)
        self._check_wick_cluster()

    def _check_wick_cluster(self):
        if self.auto_flags.get('smoke_high') or self.auto_flags.get('temp_high'):
            wick_spec = self.wax_sample.wick_spec
            test_batch = self.wax_sample.test_batch
            problem_count = BurnTest.objects.filter(
                wax_sample__wick_spec=wick_spec,
                wax_sample__test_batch=test_batch,
            ).filter(
                models.Q(auto_flags__smoke_high=True)
                | models.Q(auto_flags__temp_high=True)
            ).count()
            if problem_count >= WICK_PROBLEM_THRESHOLD:
                from samples.signals import wick_problem_detected
                wick_problem_detected.send(
                    sender=self.__class__,
                    wick_spec=wick_spec,
                    test_batch=test_batch,
                    count=problem_count
                )
