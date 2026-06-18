from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta


RETARGET_MISSING_DAYS = 7


class StatusChoices(models.TextChoices):
    PENDING_PROOFING = 'pending_proofing', '待打样'
    PENDING_TEST = 'pending_test', '待测试'
    IN_TEST = 'in_test', '测试中'
    PENDING_RETEST = 'pending_retest', '待复测'
    NEED_REFORM = 'need_reform', '需改配'
    VERSION_READY = 'version_ready', '可归入版本库'


class ClosureActionChoices(models.TextChoices):
    CONTINUE_RETEST = 'continue_retest', '继续复测'
    TRANSFER_REFORM = 'transfer_reform', '转入改配'
    CONFIRM_VERSION = 'confirm_version', '确认可归入版本库'


class SmokeLevelChoices(models.IntegerChoices):
    LEVEL_1 = 1, '1级-无烟'
    LEVEL_2 = 2, '2级-轻微'
    LEVEL_3 = 3, '3级-中等'
    LEVEL_4 = 4, '4级-偏高'
    LEVEL_5 = 5, '5级-严重'


SMOKE_HIGH_THRESHOLD = 4
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

    def has_pending_retest_missing(self):
        if self.status != StatusChoices.PENDING_RETEST:
            return False
        latest = self.latest_test
        if not latest:
            return True
        if not latest.is_retest:
            cutoff = latest.test_time + timedelta(days=RETARGET_MISSING_DAYS)
            return timezone.now() > cutoff
        return False


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

    def clean(self):
        super().clean()
        if self.ignite_time and self.extinguish_time:
            if self.extinguish_time < self.ignite_time:
                raise ValidationError({
                    'extinguish_time': '熄灭时间不能早于点燃时间，时长不可为负。'
                })

    @property
    def burn_duration_minutes(self):
        if self.ignite_time and self.extinguish_time:
            delta = self.extinguish_time - self.ignite_time
            if delta.total_seconds() < 0:
                return None
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

        if self.abnormal_desc:
            if self.enter_next_round is None:
                flags['next_round_missing'] = True
                warnings.append('存在异常但未标注是否进入下一轮')
            if self.enter_next_round is True and not self.retest_suggestion:
                flags['suggestion_missing'] = True
                warnings.append('标注进入下一轮但未填写复测建议')

        sample = self.wax_sample
        if sample_id := self.wax_sample_id:
            if sample and sample.status == StatusChoices.PENDING_RETEST:
                non_retest = sample.burn_tests.filter(is_retest=False).order_by('-test_time').first()
                if non_retest:
                    cutoff = non_retest.test_time + timedelta(days=RETARGET_MISSING_DAYS)
                    no_retest_done = not sample.burn_tests.filter(is_retest=True, test_time__gt=non_retest.test_time).exists()
                    if timezone.now() > cutoff and no_retest_done:
                        flags['retest_action_missing'] = True
                        warnings.append(f'待复测已超{RETARGET_MISSING_DAYS}天未执行')

        flags['warnings'] = warnings
        return flags

    def save(self, *args, **kwargs):
        self.full_clean()
        self.auto_flags = self.analyze_flags()
        super().save(*args, **kwargs)
        self._check_wick_cluster()
        self._update_sample_status_after_save()

    def _update_sample_status_after_save(self):
        sample = self.wax_sample
        if self.extinguish_time is None:
            if sample.status in [StatusChoices.PENDING_TEST, StatusChoices.PENDING_RETEST]:
                sample.status = StatusChoices.IN_TEST
                sample.save(update_fields=['status', 'updated_at'])
            return
        has_abnormal = bool(
            self.auto_flags.get('smoke_high')
            or self.auto_flags.get('temp_high')
            or self.abnormal_desc
        )
        if self.enter_next_round is not None:
            if self.enter_next_round:
                if self.is_retest and not has_abnormal:
                    sample.status = StatusChoices.VERSION_READY
                else:
                    sample.status = StatusChoices.PENDING_RETEST
            else:
                if has_abnormal:
                    sample.status = StatusChoices.NEED_REFORM
                else:
                    sample.status = StatusChoices.PENDING_RETEST
        else:
            if has_abnormal:
                sample.status = StatusChoices.PENDING_RETEST
            else:
                sample.status = StatusChoices.PENDING_RETEST
        sample.save(update_fields=['status', 'updated_at'])

    def _check_wick_cluster(self):
        if self.auto_flags.get('smoke_high') or self.auto_flags.get('temp_high'):
            wick_spec = self.wax_sample.wick_spec
            test_batch = self.wax_sample.test_batch
            sample_ids_q = WaxSample.objects.filter(
                wick_spec=wick_spec,
                test_batch=test_batch,
            )
            problem_sample_ids = set()
            for s in sample_ids_q.prefetch_related('burn_tests'):
                for t in s.burn_tests.all():
                    if t.auto_flags.get('smoke_high') or t.auto_flags.get('temp_high'):
                        problem_sample_ids.add(s.id)
                        break
            problem_sample_count = len(problem_sample_ids)
            if problem_sample_count >= WICK_PROBLEM_THRESHOLD:
                affected = list(
                    WaxSample.objects.filter(
                        id__in=problem_sample_ids
                    ).values_list('sample_code', flat=True)
                )
                WickProblemAlert.objects.update_or_create(
                    wick_spec=wick_spec,
                    test_batch=test_batch,
                    defaults={
                        'problem_count': problem_sample_count,
                        'affected_samples': affected,
                        'last_triggered': timezone.now(),
                        'resolved': False,
                    }
                )


class WickProblemAlert(models.Model):
    wick_spec = models.CharField('芯线规格', max_length=50)
    test_batch = models.CharField('测试批次', max_length=50)
    problem_count = models.PositiveIntegerField('问题样品数', default=0)
    affected_samples = models.JSONField('涉及蜡样', default=list, blank=True)
    last_triggered = models.DateTimeField('最后触发时间', auto_now=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True)
    resolved = models.BooleanField('是否已处理', default=False)
    note = models.TextField('处理备注', blank=True, default='')

    class Meta:
        verbose_name = '芯线问题集中告警'
        verbose_name_plural = '芯线问题集中告警'
        ordering = ['-last_triggered']
        unique_together = [['wick_spec', 'test_batch']]

    def __str__(self):
        return f'[{self.test_batch}] {self.wick_spec}: {self.problem_count}个问题'


class RetestClosure(models.Model):
    wax_sample = models.ForeignKey(
        WaxSample,
        on_delete=models.CASCADE,
        related_name='retest_closures',
        verbose_name='蜡样'
    )
    burn_test = models.ForeignKey(
        BurnTest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='closures',
        verbose_name='关联测试记录'
    )
    action = models.CharField(
        '处理结论',
        max_length=30,
        choices=ClosureActionChoices.choices
    )
    handler = models.CharField('处理人', max_length=50, blank=True, default='')
    remark = models.TextField('处理备注', blank=True, default='')
    created_at = models.DateTimeField('处理时间', auto_now_add=True)

    class Meta:
        verbose_name = '复测闭环处理记录'
        verbose_name_plural = '复测闭环处理记录'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.wax_sample} - {self.get_action_display()}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self._update_sample_status()

    def _update_sample_status(self):
        sample = self.wax_sample
        if self.action == ClosureActionChoices.CONTINUE_RETEST:
            sample.status = StatusChoices.PENDING_RETEST
        elif self.action == ClosureActionChoices.TRANSFER_REFORM:
            sample.status = StatusChoices.NEED_REFORM
        elif self.action == ClosureActionChoices.CONFIRM_VERSION:
            sample.status = StatusChoices.VERSION_READY
        sample.save(update_fields=['status', 'updated_at'])
