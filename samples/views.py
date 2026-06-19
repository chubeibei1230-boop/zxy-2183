from django.db import models
from django.db.models import Q, Count, Min, Max
from django.utils import timezone
from django.shortcuts import render
from rest_framework import viewsets, status, mixins
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination


class FlexiblePageNumberPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 500

from .models import (
    WaxSample, BurnTest, WickProblemAlert, RetestClosure,
    RetestPlan, RetestPlanExecution,
    StatusChoices, SmokeLevelChoices, ClosureActionChoices,
    PlanStatusChoices, PlanSourceChoices,
    WICK_PROBLEM_THRESHOLD, RETARGET_MISSING_DAYS
)
from .serializers import (
    WaxSampleSerializer, WaxSampleDetailSerializer,
    BurnTestSerializer, BurnTestListSerializer,
    StatusSerializer, SmokeLevelSerializer,
    ProblemWickSerializer, PendingRetestSerializer,
    DurationDistributionSerializer, WickProblemAlertSerializer,
    RetestClosureSerializer, ClosureActionSerializer,
    ClosureSampleListSerializer, ClosureSampleDetailSerializer,
    ClosureSummarySerializer, ClosureHandleSerializer,
    PlanStatusSerializer, PlanSourceSerializer,
    RetestPlanSerializer, RetestPlanListSerializer, RetestPlanDetailSerializer,
    RetestPlanExecutionSerializer, RetestPlanExecutionListSerializer,
    RetestPlanExecuteSerializer, RetestPlanCancelSerializer,
    PlanSummarySerializer,
    ReviewReportSummarySerializer, ReviewAbnormalSampleSerializer,
    ReviewWickRankingSerializer, ReviewUnclosedItemSerializer,
    ReviewClosedRecordSerializer, ReviewSampleDetailSerializer,
    AbnormalTypeSerializer, ProcessingStatusSerializer
)
from .filters import (
    WaxSampleFilter, BurnTestFilter, ClosureSampleFilter,
    RetestClosureFilter, RetestPlanFilter, RetestPlanExecutionFilter,
    ReviewReportFilter
)


class WaxSampleViewSet(viewsets.ModelViewSet):
    queryset = WaxSample.objects.select_related().prefetch_related('burn_tests')
    pagination_class = FlexiblePageNumberPagination
    filterset_class = WaxSampleFilter
    search_fields = [
        'sample_code', 'test_batch', 'fragrance_code',
        'wick_spec', 'cup_type', 'responsible_person'
    ]
    ordering_fields = [
        'created_at', 'updated_at', 'test_batch',
        'sample_code', 'status'
    ]
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return WaxSampleDetailSerializer
        return WaxSampleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.annotate(
            _latest_test_time=Max('burn_tests__test_time')
        )
        return qs

    @action(detail=True, methods=['post'], url_path='update-status')
    def update_status(self, request, pk=None):
        sample = self.get_object()
        new_status = request.data.get('status')
        if new_status not in dict(StatusChoices.choices):
            return Response(
                {'error': f'无效状态: {new_status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        old_status = sample.status
        sample.status = new_status
        sample.save(update_fields=['status', 'updated_at'])
        return Response({
            'id': sample.id,
            'old_status': old_status,
            'new_status': new_status,
            'status_display': sample.get_status_display()
        })

    @action(detail=False, methods=['get'], url_path='status-options')
    def status_options(self, request):
        data = [{'value': v, 'label': l} for v, l in StatusChoices.choices]
        return Response(StatusSerializer(data, many=True).data)

    @action(detail=False, methods=['get'], url_path='smoke-level-options')
    def smoke_level_options(self, request):
        data = [{'value': v, 'label': l} for v, l in SmokeLevelChoices.choices]
        return Response(SmokeLevelSerializer(data, many=True).data)

    @action(detail=False, methods=['get'], url_path='overview-summary')
    def overview_summary(self, request):
        total = WaxSample.objects.count()
        by_status = WaxSample.objects.values('status').annotate(
            count=Count('id')
        ).order_by('status')
        status_map = {}
        for item in by_status:
            status_map[item['status']] = item['count']
        status_summary = []
        for v, l in StatusChoices.choices:
            status_summary.append({
                'value': v,
                'label': l,
                'count': status_map.get(v, 0)
            })
        total_tests = BurnTest.objects.count()
        abnormal_tests = BurnTest.objects.filter(
            Q(auto_flags__smoke_high=True)
            | Q(auto_flags__temp_high=True)
            | Q(abnormal_desc__gt='')
        ).count()
        wick_alerts = WickProblemAlert.objects.filter(resolved=False).count()
        return Response({
            'total_samples': total,
            'total_tests': total_tests,
            'abnormal_tests': abnormal_tests,
            'pending_wick_alerts': wick_alerts,
            'status_summary': status_summary
        })


class BurnTestViewSet(viewsets.ModelViewSet):
    queryset = BurnTest.objects.select_related('wax_sample').all()
    pagination_class = FlexiblePageNumberPagination
    filterset_class = BurnTestFilter
    search_fields = [
        'wax_sample__sample_code', 'wax_sample__test_batch',
        'wax_sample__fragrance_code', 'wax_sample__wick_spec',
        'tested_by', 'abnormal_desc', 'retest_suggestion'
    ]
    ordering_fields = [
        'test_time', 'ignite_time', 'smoke_level',
        'cup_wall_temp', 'test_round'
    ]
    ordering = ['-test_time']

    def get_serializer_class(self):
        if self.action in ['list']:
            return BurnTestListSerializer
        return BurnTestSerializer

    def create(self, request, *args, **kwargs):
        sample_id = request.data.get('wax_sample')
        if sample_id:
            try:
                sample = WaxSample.objects.get(id=sample_id)
            except WaxSample.DoesNotExist:
                return Response(
                    {'error': '蜡样不存在'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            existing_rounds = sample.burn_tests.count()
            is_retest = request.data.get('is_retest', False)
            if not request.data.get('test_round'):
                request.data['test_round'] = existing_rounds + 1
            if is_retest and sample.status not in [StatusChoices.PENDING_RETEST, StatusChoices.IN_TEST]:
                sample.status = StatusChoices.PENDING_RETEST
                sample.save(update_fields=['status', 'updated_at'])
        return super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    @action(detail=False, methods=['get'], url_path='abnormal-alerts')
    def abnormal_alerts(self, request):
        alerts = []
        smoke_high = BurnTest.objects.filter(
            auto_flags__smoke_high=True
        ).select_related('wax_sample')[:20]
        for t in smoke_high:
            alerts.append({
                'type': 'smoke_high',
                'message': f'{t.wax_sample.sample_code} 烟量偏高(等级{t.smoke_level})',
                'wax_sample_id': t.wax_sample_id,
                'test_id': t.id,
                'test_time': t.test_time
            })
        temp_high = BurnTest.objects.filter(
            auto_flags__temp_high=True
        ).select_related('wax_sample')[:20]
        for t in temp_high:
            alerts.append({
                'type': 'temp_high',
                'message': f'{t.wax_sample.sample_code} 杯壁温度偏高({t.cup_wall_temp}℃)',
                'wax_sample_id': t.wax_sample_id,
                'test_id': t.id,
                'test_time': t.test_time
            })
        temp_low = BurnTest.objects.filter(
            auto_flags__temp_low=True
        ).select_related('wax_sample')[:20]
        for t in temp_low:
            alerts.append({
                'type': 'temp_low',
                'message': f'{t.wax_sample.sample_code} 杯壁温度偏低({t.cup_wall_temp}℃)',
                'wax_sample_id': t.wax_sample_id,
                'test_id': t.id,
                'test_time': t.test_time
            })
        next_round_missing = BurnTest.objects.filter(
            auto_flags__next_round_missing=True
        ).select_related('wax_sample')[:20]
        for t in next_round_missing:
            alerts.append({
                'type': 'next_round_missing',
                'message': f'{t.wax_sample.sample_code} 存在异常但未标注是否进入下一轮',
                'wax_sample_id': t.wax_sample_id,
                'test_id': t.id,
                'test_time': t.test_time
            })
        suggestion_missing = BurnTest.objects.filter(
            auto_flags__suggestion_missing=True
        ).select_related('wax_sample')[:20]
        for t in suggestion_missing:
            alerts.append({
                'type': 'suggestion_missing',
                'message': f'{t.wax_sample.sample_code} 标注进入下一轮但缺少复测建议',
                'wax_sample_id': t.wax_sample_id,
                'test_id': t.id,
                'test_time': t.test_time
            })
        retest_action_missing = BurnTest.objects.filter(
            auto_flags__retest_action_missing=True
        ).select_related('wax_sample')[:20]
        for t in retest_action_missing:
            alerts.append({
                'type': 'retest_action_missing',
                'message': f'{t.wax_sample.sample_code} 待复测超期未执行',
                'wax_sample_id': t.wax_sample_id,
                'test_id': t.id,
                'test_time': t.test_time
            })
        alerted_retest_sample_ids = {
            a['wax_sample_id'] for a in alerts
            if a.get('type') == 'retest_action_missing'
        }
        overdue_retest_samples = WaxSample.objects.filter(
            status=StatusChoices.PENDING_RETEST
        ).prefetch_related('burn_tests')[:100]
        for sample in overdue_retest_samples:
            if sample.id in alerted_retest_sample_ids:
                continue
            if not sample.has_pending_retest_missing():
                continue
            latest = sample.latest_test
            alerts.append({
                'type': 'retest_action_missing',
                'message': f'{sample.sample_code} 待复测超期未执行',
                'wax_sample_id': sample.id,
                'test_id': latest.id if latest else None,
                'test_time': latest.test_time if latest else None
            })
        wick_alerts = WickProblemAlert.objects.filter(resolved=False).order_by('-last_triggered')[:20]
        for a in wick_alerts:
            samples_str = '、'.join(a.affected_samples) if a.affected_samples else '无'
            alerts.append({
                'type': 'wick_problem_cluster',
                'message': f'[{a.test_batch}] 芯线{a.wick_spec} 问题集中({a.problem_count}条问题，涉及：{samples_str})',
                'wick_spec': a.wick_spec,
                'test_batch': a.test_batch,
                'alert_id': a.id,
                'last_triggered': a.last_triggered,
                'problem_count': a.problem_count,
                'affected_samples': a.affected_samples
            })
        return Response({'count': len(alerts), 'alerts': alerts})


class WickProblemAlertViewSet(viewsets.ModelViewSet):
    queryset = WickProblemAlert.objects.all().order_by('-last_triggered')
    serializer_class = WickProblemAlertSerializer
    pagination_class = FlexiblePageNumberPagination
    filterset_fields = ['wick_spec', 'test_batch', 'resolved']
    search_fields = ['wick_spec', 'test_batch', 'note']
    ordering_fields = ['last_triggered', 'problem_count', 'created_at']

    @action(detail=True, methods=['post'], url_path='resolve')
    def resolve_alert(self, request, pk=None):
        alert = self.get_object()
        alert.resolved = True
        alert.note = request.data.get('note', alert.note)
        alert.save(update_fields=['resolved', 'note', 'last_triggered'])
        return Response(WickProblemAlertSerializer(alert).data)


class ProblemWickRankingView(APIView):
    def get(self, request):
        test_batch = request.query_params.get('test_batch')
        limit = int(request.query_params.get('limit', 10))

        base_qs = BurnTest.objects.select_related('wax_sample').filter(
            Q(auto_flags__smoke_high=True) | Q(auto_flags__temp_high=True)
        )
        if test_batch:
            base_qs = base_qs.filter(wax_sample__test_batch=test_batch)

        wick_stats = base_qs.values('wax_sample__wick_spec').annotate(
            problem_count=Count('id', distinct=True),
            min_time=Min('test_time'),
            max_time=Max('test_time')
        ).order_by('-problem_count')[:limit]

        result = []
        for stat in wick_stats:
            wick_spec = stat['wax_sample__wick_spec']
            wick_samples_query = WaxSample.objects.filter(wick_spec=wick_spec)
            if test_batch:
                wick_samples_query = wick_samples_query.filter(test_batch=test_batch)
            total_samples = wick_samples_query.count()

            problem_tests = base_qs.filter(wax_sample__wick_spec=wick_spec)
            affected_ids = list(problem_tests.values_list('wax_sample_id', flat=True).distinct())
            affected_samples = WaxSample.objects.filter(id__in=affected_ids).values(
                'id', 'sample_code', 'test_batch', 'fragrance_code', 'cup_type'
            )

            problem_rate = round(stat['problem_count'] / total_samples * 100, 1) if total_samples > 0 else 0

            result.append({
                'wick_spec': wick_spec,
                'problem_count': stat['problem_count'],
                'total_samples': total_samples,
                'affected_samples': list(affected_samples),
                'problem_rate': problem_rate
            })
        serializer = ProblemWickSerializer(result, many=True)
        return Response(serializer.data)


class PendingRetestView(APIView):
    def get(self, request):
        status_filter = request.query_params.get('status')
        fragrance_code = request.query_params.get('fragrance_code')
        wick_spec = request.query_params.get('wick_spec')
        only_overdue = request.query_params.get('only_overdue')

        samples = WaxSample.objects.filter(
            Q(status=StatusChoices.PENDING_RETEST) |
            Q(status=StatusChoices.NEED_REFORM)
        ).select_related().prefetch_related('burn_tests')

        if status_filter:
            samples = samples.filter(status=status_filter)
        if fragrance_code:
            samples = samples.filter(fragrance_code__icontains=fragrance_code)
        if wick_spec:
            samples = samples.filter(wick_spec__icontains=wick_spec)

        result = []
        for s in samples:
            abnormal_tests = s.burn_tests.filter(
                Q(auto_flags__smoke_high=True) |
                Q(auto_flags__temp_high=True) |
                Q(abnormal_desc__gt='')
            )
            abnormal_count = abnormal_tests.count()
            latest = s.burn_tests.order_by('-test_time').first()
            last_test_time = latest.test_time if latest else None
            latest_suggestion = latest.retest_suggestion if latest and latest.retest_suggestion else None

            overdue = s.has_pending_retest_missing()
            if only_overdue and not overdue:
                continue

            result.append({
                    'id': s.id,
                    'sample_code': s.sample_code,
                    'cup_type': s.cup_type,
                    'fragrance_code': s.fragrance_code,
                    'wick_spec': s.wick_spec,
                    'test_batch': s.test_batch,
                    'responsible_person': s.responsible_person,
                    'status_display': s.get_status_display(),
                    'abnormal_count': abnormal_count,
                    'last_test_time': last_test_time,
                    'latest_suggestion': latest_suggestion,
                    'retest_overdue': overdue,
                })

        serializer = PendingRetestSerializer(result, many=True)
        return Response({
            'count': len(result),
            'results': serializer.data
        })


class TestDurationDistributionView(APIView):
    def get(self, request):
        ranges = [
            (0, 30, '0-30分钟'),
            (30, 60, '30-60分钟'),
            (60, 120, '1-2小时'),
            (120, 180, '2-3小时'),
            (180, 240, '3-4小时'),
            (240, None, '4小时以上'),
        ]
        tests_qs = BurnTest.objects.filter(
            ignite_time__isnull=False,
            extinguish_time__isnull=False
        )
        durations = []
        negative_count = 0
        for t in tests_qs:
            d = (t.extinguish_time - t.ignite_time).total_seconds() / 60
            if d >= 0:
                durations.append(d)
            else:
                negative_count += 1

        total = len(durations)
        result = []
        for r_min, r_max, label in ranges:
            if r_max is None:
                count = sum(1 for d in durations if d >= r_min)
            else:
                count = sum(1 for d in durations if r_min <= d < r_max)
            percentage = round(count / total * 100, 1) if total > 0 else 0
            result.append({
                'range_label': label,
                'range_min': r_min,
                'range_max': r_max,
                'count': count,
                'percentage': percentage
            })

        serializer = DurationDistributionSerializer(result, many=True)
        stats = {}
        if durations:
            stats = {
                'total_valid': total,
                'excluded_negative': negative_count,
                'avg_minutes': round(sum(durations) / total, 1),
                'min_minutes': round(min(durations), 1),
                'max_minutes': round(max(durations), 1),
            }
        return Response({
            'statistics': stats,
            'distribution': serializer.data
        })


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    return Response({
        'status': 'ok',
        'service': '香氛蜡样研发管理系统',
        'version': '1.1.0',
        'timestamp': timezone.now()
    })


@permission_classes([AllowAny])
def closure_dashboard(request):
    return render(request, 'samples/closure_dashboard.html')


class RetestClosureViewSet(viewsets.ModelViewSet):
    queryset = RetestClosure.objects.select_related('wax_sample', 'burn_test').all()
    serializer_class = RetestClosureSerializer
    pagination_class = FlexiblePageNumberPagination
    filterset_class = RetestClosureFilter
    search_fields = [
        'wax_sample__sample_code', 'wax_sample__test_batch',
        'wax_sample__wick_spec', 'handler', 'remark'
    ]
    ordering_fields = ['created_at', 'action']
    ordering = ['-created_at']


class ClosureSampleViewSet(viewsets.ReadOnlyModelViewSet):
    pagination_class = FlexiblePageNumberPagination
    filterset_class = ClosureSampleFilter
    search_fields = [
        'sample_code', 'test_batch', 'fragrance_code',
        'wick_spec', 'cup_type', 'responsible_person'
    ]
    ordering_fields = [
        'created_at', 'updated_at', 'test_batch',
        'sample_code', 'status'
    ]
    ordering = ['-updated_at']

    def get_queryset(self):
        return WaxSample.objects.filter(
            Q(status=StatusChoices.PENDING_RETEST)
            | Q(status=StatusChoices.NEED_REFORM)
        ).select_related().prefetch_related(
            'burn_tests', 'retest_closures'
        )

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ClosureSampleDetailSerializer
        return ClosureSampleListSerializer

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            results = self._build_list_data(page)
            serializer = self.get_serializer(results, many=True)
            return self.get_paginated_response(serializer.data)
        results = self._build_list_data(queryset)
        serializer = self.get_serializer(results, many=True)
        return Response({
            'count': len(results),
            'results': serializer.data
        })

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        data = self._build_detail_data(instance)
        serializer = self.get_serializer(data)
        return Response(serializer.data)

    def _build_list_data(self, samples):
        unresolved_alerts = WickProblemAlert.objects.filter(resolved=False)
        alert_key_set = set()
        for a in unresolved_alerts:
            alert_key_set.add((a.test_batch, a.wick_spec))
        results = []
        for s in samples:
            abnormal_tests = s.burn_tests.filter(
                Q(auto_flags__smoke_high=True)
                | Q(auto_flags__temp_high=True)
                | Q(abnormal_desc__gt='')
            )
            abnormal_count = abnormal_tests.count()
            latest = s.burn_tests.order_by('-test_time').first()
            last_test_time = latest.test_time if latest else None
            latest_suggestion = latest.retest_suggestion if latest and latest.retest_suggestion else None
            overdue = s.has_pending_retest_missing()
            has_wick_alert = (s.test_batch, s.wick_spec) in alert_key_set
            results.append({
                'id': s.id,
                'sample_code': s.sample_code,
                'cup_type': s.cup_type,
                'fragrance_code': s.fragrance_code,
                'wick_spec': s.wick_spec,
                'test_batch': s.test_batch,
                'responsible_person': s.responsible_person,
                'status': s.status,
                'status_display': s.get_status_display(),
                'abnormal_count': abnormal_count,
                'last_test_time': last_test_time,
                'latest_suggestion': latest_suggestion,
                'retest_overdue': overdue,
                'has_wick_alert': has_wick_alert,
                'retest_count': s.retest_count,
            })
        return results

    def _build_detail_data(self, s):
        abnormal_tests = s.burn_tests.filter(
            Q(auto_flags__smoke_high=True)
            | Q(auto_flags__temp_high=True)
            | Q(abnormal_desc__gt='')
        )
        abnormal_count = abnormal_tests.count()
        latest = s.burn_tests.order_by('-test_time').first()
        overdue = s.has_pending_retest_missing()
        wick_alerts = WickProblemAlert.objects.filter(
            test_batch=s.test_batch,
            wick_spec=s.wick_spec
        ).order_by('-last_triggered')
        closure_history = s.retest_closures.order_by('-created_at')
        return {
            'id': s.id,
            'sample_code': s.sample_code,
            'test_batch': s.test_batch,
            'fragrance_code': s.fragrance_code,
            'cup_type': s.cup_type,
            'wick_spec': s.wick_spec,
            'responsible_person': s.responsible_person,
            'status': s.status,
            'status_display': s.get_status_display(),
            'created_at': s.created_at,
            'updated_at': s.updated_at,
            'remarks': s.remarks,
            'latest_test': latest,
            'wick_alerts': wick_alerts,
            'closure_history': closure_history,
            'retest_overdue': overdue,
            'abnormal_count': abnormal_count,
        }

    @action(detail=True, methods=['post'], url_path='handle')
    def handle_sample(self, request, pk=None):
        sample = self.get_object()
        serializer = ClosureHandleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        burn_test = None
        if data.get('burn_test_id'):
            try:
                burn_test = BurnTest.objects.get(id=data['burn_test_id'], wax_sample=sample)
            except BurnTest.DoesNotExist:
                return Response(
                    {'error': '关联的测试记录不存在或不属于该蜡样'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        closure = RetestClosure.objects.create(
            wax_sample=sample,
            burn_test=burn_test,
            action=data['action'],
            handler=data.get('handler', ''),
            remark=data.get('remark', '')
        )
        return Response({
            'closure_id': closure.id,
            'new_status': sample.status,
            'new_status_display': sample.get_status_display(),
            'action': closure.action,
            'action_display': closure.get_action_display()
        })

    @action(detail=False, methods=['get'], url_path='action-options')
    def action_options(self, request):
        data = [{'value': v, 'label': l} for v, l in ClosureActionChoices.choices]
        return Response(ClosureActionSerializer(data, many=True).data)


class ClosureSummaryView(APIView):
    def get(self, request):
        pending_retest_qs = WaxSample.objects.filter(status=StatusChoices.PENDING_RETEST)
        pending_retest_count = pending_retest_qs.count()
        overdue_retest_count = 0
        for s in pending_retest_qs.prefetch_related('burn_tests'):
            if s.has_pending_retest_missing():
                overdue_retest_count += 1
        need_reform_count = WaxSample.objects.filter(status=StatusChoices.NEED_REFORM).count()
        unresolved_wick_alerts = WickProblemAlert.objects.filter(resolved=False).count()
        abnormal_alerts_count = BurnTest.objects.filter(
            Q(auto_flags__smoke_high=True)
            | Q(auto_flags__temp_high=True)
            | Q(abnormal_desc__gt='')
        ).count()

        from datetime import timedelta
        today = timezone.now().date()
        trend_days = int(request.query_params.get('trend_days', 7))
        trend_list = []
        for i in range(trend_days - 1, -1, -1):
            d = today - timedelta(days=i)
            day_tests = BurnTest.objects.filter(test_time__date=d)
            abnormal = day_tests.filter(
                Q(auto_flags__smoke_high=True)
                | Q(auto_flags__temp_high=True)
                | Q(abnormal_desc__gt='')
            ).count()
            smoke_high = day_tests.filter(auto_flags__smoke_high=True).count()
            temp_high = day_tests.filter(auto_flags__temp_high=True).count()
            retest = day_tests.filter(is_retest=True).count()
            trend_list.append({
                'date': d,
                'abnormal_count': abnormal,
                'smoke_high_count': smoke_high,
                'temp_high_count': temp_high,
                'retest_count': retest,
            })

        by_batch = WaxSample.objects.filter(
            Q(status=StatusChoices.PENDING_RETEST)
            | Q(status=StatusChoices.NEED_REFORM)
        ).values('test_batch').annotate(
            pending_count=Count('id', filter=Q(status=StatusChoices.PENDING_RETEST)),
            reform_count=Count('id', filter=Q(status=StatusChoices.NEED_REFORM)),
            total=Count('id')
        ).order_by('-total')[:5]
        by_batch_top5 = list(by_batch)

        by_wick = WaxSample.objects.filter(
            Q(status=StatusChoices.PENDING_RETEST)
            | Q(status=StatusChoices.NEED_REFORM)
        ).values('wick_spec').annotate(
            pending_count=Count('id', filter=Q(status=StatusChoices.PENDING_RETEST)),
            reform_count=Count('id', filter=Q(status=StatusChoices.NEED_REFORM)),
            total=Count('id')
        ).order_by('-total')[:5]
        by_wick_top5 = list(by_wick)

        result = {
            'pending_retest_count': pending_retest_count,
            'overdue_retest_count': overdue_retest_count,
            'need_reform_count': need_reform_count,
            'unresolved_wick_alerts': unresolved_wick_alerts,
            'abnormal_alerts_count': abnormal_alerts_count,
            'recent_abnormal_trend': trend_list,
            'by_batch_top5': by_batch_top5,
            'by_wick_top5': by_wick_top5,
        }
        serializer = ClosureSummarySerializer(result)
        return Response(serializer.data)


class RetestPlanViewSet(viewsets.ModelViewSet):
    queryset = RetestPlan.objects.select_related('wax_sample', 'source_burn_test').prefetch_related(
        'executions', 'wax_sample__burn_tests', 'wax_sample__retest_closures'
    )
    pagination_class = FlexiblePageNumberPagination
    filterset_class = RetestPlanFilter
    search_fields = [
        'plan_no', 'wax_sample__sample_code', 'wax_sample__test_batch',
        'wax_sample__fragrance_code', 'wax_sample__wick_spec',
        'wax_sample__cup_type', 'responsible_person', 'retest_goal',
        'attention_notes', 'source_reason_detail'
    ]
    ordering_fields = [
        'created_at', 'updated_at', 'planned_retest_time', 'plan_status',
        'responsible_person'
    ]
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return RetestPlanDetailSerializer
        if self.action == 'list':
            return RetestPlanListSerializer
        return RetestPlanSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        return qs

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        wax_sample_id = request.data.get('wax_sample')
        if wax_sample_id:
            try:
                sample = WaxSample.objects.get(id=wax_sample_id)
            except WaxSample.DoesNotExist:
                return Response(
                    {'error': '蜡样不存在'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=['get'], url_path='status-options')
    def status_options(self, request):
        data = [{'value': v, 'label': l} for v, l in PlanStatusChoices.choices]
        return Response(PlanStatusSerializer(data, many=True).data)

    @action(detail=False, methods=['get'], url_path='source-options')
    def source_options(self, request):
        data = [{'value': v, 'label': l} for v, l in PlanSourceChoices.choices]
        return Response(PlanSourceSerializer(data, many=True).data)

    @action(detail=True, methods=['post'], url_path='execute')
    def execute_plan(self, request, pk=None):
        plan = self.get_object()
        if plan.plan_status == PlanStatusChoices.CANCELLED:
            return Response(
                {'error': '计划已取消，不可执行'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if plan.plan_status == PlanStatusChoices.COMPLETED:
            return Response(
                {'error': '计划已完成，不可再次执行'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = RetestPlanExecuteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        burn_test = None
        if data.get('burn_test_id'):
            try:
                burn_test = BurnTest.objects.get(
                    id=data['burn_test_id'],
                    wax_sample=plan.wax_sample
                )
            except BurnTest.DoesNotExist:
                return Response(
                    {'error': '关联的测试记录不存在或不属于该蜡样'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        execution = RetestPlanExecution.objects.create(
            retest_plan=plan,
            burn_test=burn_test,
            actual_retest_time=data['actual_retest_time'],
            executed_by=data.get('executed_by', ''),
            result_description=data.get('result_description', ''),
            closure_action=data.get('closure_action'),
            closure_remark=data.get('closure_remark', '')
        )

        return Response({
            'execution_id': execution.id,
            'plan_status': plan.plan_status,
            'plan_status_display': plan.get_plan_status_display(),
            'closure_action': execution.closure_action,
            'closure_action_display': execution.get_closure_action_display() if execution.closure_action else None,
            'sample_status': plan.wax_sample.status,
            'sample_status_display': plan.wax_sample.get_status_display(),
        })

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel_plan(self, request, pk=None):
        plan = self.get_object()
        if plan.plan_status in [PlanStatusChoices.COMPLETED, PlanStatusChoices.CANCELLED]:
            return Response(
                {'error': f'计划状态为{plan.get_plan_status_display()}，不可取消'},
                status=status.HTTP_400_BAD_REQUEST
            )
        serializer = RetestPlanCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan.cancelled_reason = serializer.validated_data['cancelled_reason']
        plan.plan_status = PlanStatusChoices.CANCELLED
        plan.save(update_fields=['plan_status', 'cancelled_reason', 'updated_at'])
        return Response({
            'plan_id': plan.id,
            'plan_status': plan.plan_status,
            'plan_status_display': plan.get_plan_status_display(),
        })

    @action(detail=False, methods=['get'], url_path='summary')
    def plan_summary(self, request):
        total_plans = RetestPlan.objects.count()
        planned_count = RetestPlan.objects.filter(plan_status=PlanStatusChoices.PLANNED).count()
        in_progress_count = RetestPlan.objects.filter(plan_status=PlanStatusChoices.IN_PROGRESS).count()
        completed_count = RetestPlan.objects.filter(plan_status=PlanStatusChoices.COMPLETED).count()
        cancelled_count = RetestPlan.objects.filter(plan_status=PlanStatusChoices.CANCELLED).count()

        overdue_count = 0
        now = timezone.now()
        for plan in RetestPlan.objects.filter(
            plan_status__in=[PlanStatusChoices.PLANNED, PlanStatusChoices.IN_PROGRESS]
        ):
            if now > plan.planned_retest_time:
                overdue_count += 1

        by_status = []
        for v, l in PlanStatusChoices.choices:
            cnt = RetestPlan.objects.filter(plan_status=v).count()
            by_status.append({'value': v, 'label': l, 'count': cnt})

        by_source = []
        for v, l in PlanSourceChoices.choices:
            cnt = RetestPlan.objects.filter(source_reason=v).count()
            by_source.append({'value': v, 'label': l, 'count': cnt})

        by_responsible_qs = RetestPlan.objects.values('responsible_person').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        by_responsible = list(by_responsible_qs)

        recent_plans_qs = RetestPlan.objects.select_related('wax_sample').order_by('-created_at')[:10]
        recent_plans = []
        for p in recent_plans_qs:
            recent_plans.append({
                'id': p.id,
                'plan_no': p.plan_no,
                'plan_status': p.plan_status,
                'plan_status_display': p.get_plan_status_display(),
                'sample_code': p.wax_sample.sample_code,
                'test_batch': p.wax_sample.test_batch,
                'planned_retest_time': p.planned_retest_time,
                'responsible_person': p.responsible_person,
            })

        result = {
            'total_plans': total_plans,
            'planned_count': planned_count,
            'in_progress_count': in_progress_count,
            'completed_count': completed_count,
            'cancelled_count': cancelled_count,
            'overdue_count': overdue_count,
            'by_status': by_status,
            'by_source': by_source,
            'by_responsible': by_responsible,
            'recent_plans': recent_plans,
        }
        serializer = PlanSummarySerializer(result)
        return Response(serializer.data)


class RetestPlanExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = RetestPlanExecution.objects.select_related(
        'retest_plan', 'retest_plan__wax_sample', 'burn_test'
    ).all()
    pagination_class = FlexiblePageNumberPagination
    filterset_class = RetestPlanExecutionFilter
    search_fields = [
        'retest_plan__plan_no', 'retest_plan__wax_sample__sample_code',
        'retest_plan__wax_sample__test_batch', 'executed_by',
        'result_description', 'closure_remark'
    ]
    ordering_fields = [
        'created_at', 'actual_retest_time', 'executed_by', 'closure_action'
    ]
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return RetestPlanExecutionListSerializer
        return RetestPlanExecutionSerializer


@permission_classes([AllowAny])
def retest_plan_dashboard(request):
    return render(request, 'samples/retest_plan_dashboard.html')


@permission_classes([AllowAny])
def review_report_dashboard(request):
    return render(request, 'samples/review_report_dashboard.html')


class ReviewReportMixin:
    def get_filtered_samples(self, request):
        queryset = WaxSample.objects.select_related().prefetch_related(
            'burn_tests', 'retest_closures', 'retest_plans'
        )
        filterset = ReviewReportFilter(request.query_params, queryset=queryset)
        return filterset.qs

    def get_filtered_tests(self, samples_qs):
        return BurnTest.objects.filter(wax_sample__in=samples_qs)

    def _is_sample_closed(self, sample):
        latest_closure = sample.retest_closures.order_by('-created_at').first()
        if latest_closure and latest_closure.action in [
            ClosureActionChoices.CONFIRM_VERSION,
            ClosureActionChoices.TRANSFER_REFORM
        ]:
            return True
        return False

    def _get_sample_abnormal_types(self, sample):
        types = set()
        for t in sample.burn_tests.all():
            flags = t.analyze_flags()
            if flags.get('smoke_high'):
                types.add('烟量偏高')
            if flags.get('temp_high'):
                types.add('杯壁温度偏高')
            if flags.get('temp_low'):
                types.add('杯壁温度偏低')
            if t.abnormal_desc:
                types.add('人工异常描述')
        return list(types)

    def _count_sample_abnormal(self, sample):
        count = 0
        for t in sample.burn_tests.all():
            flags = t.analyze_flags()
            has_abnormal = (
                flags.get('smoke_high')
                or flags.get('temp_high')
                or flags.get('temp_low')
                or t.abnormal_desc
            )
            if has_abnormal:
                count += 1
        return count


class ReviewReportSummaryView(APIView, ReviewReportMixin):
    def get(self, request):
        samples_qs = self.get_filtered_samples(request)
        tests_qs = self.get_filtered_tests(samples_qs)

        total_samples = samples_qs.count()
        total_tests = tests_qs.count()

        smoke_high_count = tests_qs.filter(auto_flags__smoke_high=True).count()
        temp_high_count = tests_qs.filter(auto_flags__temp_high=True).count()
        temp_low_count = tests_qs.filter(auto_flags__temp_low=True).count()
        abnormal_desc_count = tests_qs.filter(abnormal_desc__gt='').count()

        abnormal_sample_ids = set()
        abnormal_test_count = 0
        for t in tests_qs:
            flags = t.analyze_flags()
            has_abnormal = (
                flags.get('smoke_high')
                or flags.get('temp_high')
                or flags.get('temp_low')
                or t.abnormal_desc
            )
            if has_abnormal:
                abnormal_test_count += 1
                abnormal_sample_ids.add(t.wax_sample_id)

        abnormal_sample_count = len(abnormal_sample_ids)
        abnormal_rate = round(abnormal_sample_count / total_samples * 100, 1) if total_samples > 0 else 0

        by_status = []
        for v, l in StatusChoices.choices:
            cnt = samples_qs.filter(status=v).count()
            by_status.append({'value': v, 'label': l, 'count': cnt})

        pending_retest_count = samples_qs.filter(status=StatusChoices.PENDING_RETEST).count()
        need_reform_count = samples_qs.filter(status=StatusChoices.NEED_REFORM).count()
        version_ready_count = samples_qs.filter(status=StatusChoices.VERSION_READY).count()

        test_batch_set = set(samples_qs.values_list('test_batch', flat=True).distinct())
        wick_spec_set = set(samples_qs.values_list('wick_spec', flat=True).distinct())
        unresolved_wick_alerts = WickProblemAlert.objects.filter(
            resolved=False,
            test_batch__in=test_batch_set,
            wick_spec__in=wick_spec_set
        ).count()

        closed_count = 0
        unclosed_count = 0
        for s in samples_qs.prefetch_related('retest_closures', 'burn_tests'):
            has_abnormal = False
            for t in s.burn_tests.all():
                flags = t.analyze_flags()
                if (flags.get('smoke_high') or flags.get('temp_high')
                        or flags.get('temp_low') or t.abnormal_desc):
                    has_abnormal = True
                    break
            if not has_abnormal:
                continue
            if self._is_sample_closed(s):
                closed_count += 1
            else:
                unclosed_count += 1

        total_abnormal = closed_count + unclosed_count
        closure_rate = round(closed_count / total_abnormal * 100, 1) if total_abnormal > 0 else 0

        by_abnormal_type = [
            {'value': 'smoke_high', 'label': '烟量偏高', 'count': smoke_high_count},
            {'value': 'temp_high', 'label': '杯壁温度偏高', 'count': temp_high_count},
            {'value': 'temp_low', 'label': '杯壁温度偏低', 'count': temp_low_count},
            {'value': 'abnormal_desc', 'label': '人工异常描述', 'count': abnormal_desc_count},
        ]

        by_fragrance_qs = samples_qs.values('fragrance_code').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        by_fragrance = [
            {'fragrance_code': item['fragrance_code'], 'count': item['count']}
            for item in by_fragrance_qs
        ]

        by_cup_type_qs = samples_qs.values('cup_type').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        by_cup_type = [
            {'cup_type': item['cup_type'], 'count': item['count']}
            for item in by_cup_type_qs
        ]

        by_responsible_qs = samples_qs.values('responsible_person').annotate(
            count=Count('id')
        ).order_by('-count')[:10]
        by_responsible = [
            {'responsible_person': item['responsible_person'], 'count': item['count']}
            for item in by_responsible_qs
        ]

        plans_qs = RetestPlan.objects.filter(wax_sample__in=samples_qs)
        retest_plans_total = plans_qs.count()
        retest_plans_completed = plans_qs.filter(plan_status=PlanStatusChoices.COMPLETED).count()
        retest_plans_pending = plans_qs.filter(
            plan_status__in=[PlanStatusChoices.PLANNED, PlanStatusChoices.IN_PROGRESS]
        ).count()

        now = timezone.now()
        retest_plans_overdue = 0
        for p in plans_qs.filter(plan_status__in=[PlanStatusChoices.PLANNED, PlanStatusChoices.IN_PROGRESS]):
            if now > p.planned_retest_time:
                retest_plans_overdue += 1

        result = {
            'total_samples': total_samples,
            'total_tests': total_tests,
            'abnormal_sample_count': abnormal_sample_count,
            'abnormal_test_count': abnormal_test_count,
            'abnormal_rate': abnormal_rate,
            'smoke_high_count': smoke_high_count,
            'temp_high_count': temp_high_count,
            'temp_low_count': temp_low_count,
            'pending_retest_count': pending_retest_count,
            'need_reform_count': need_reform_count,
            'version_ready_count': version_ready_count,
            'unresolved_wick_alerts': unresolved_wick_alerts,
            'unclosed_count': unclosed_count,
            'closed_count': closed_count,
            'closure_rate': closure_rate,
            'retest_plans_total': retest_plans_total,
            'retest_plans_completed': retest_plans_completed,
            'retest_plans_pending': retest_plans_pending,
            'retest_plans_overdue': retest_plans_overdue,
            'by_status': by_status,
            'by_abnormal_type': by_abnormal_type,
            'by_fragrance': by_fragrance,
            'by_cup_type': by_cup_type,
            'by_responsible': by_responsible,
        }
        serializer = ReviewReportSummarySerializer(result)
        return Response(serializer.data)


class ReviewAbnormalSampleListView(APIView, ReviewReportMixin):
    pagination_class = FlexiblePageNumberPagination

    @property
    def paginator(self):
        if not hasattr(self, '_paginator'):
            self._paginator = self.pagination_class()
        return self._paginator

    def get(self, request):
        samples_qs = self.get_filtered_samples(request)
        test_batch_set = set(samples_qs.values_list('test_batch', flat=True).distinct())
        wick_spec_set = set(samples_qs.values_list('wick_spec', flat=True).distinct())
        alert_map = set()
        for a in WickProblemAlert.objects.filter(
            resolved=False,
            test_batch__in=test_batch_set,
            wick_spec__in=wick_spec_set
        ):
            alert_map.add((a.test_batch, a.wick_spec))

        abnormal_samples = []
        for s in samples_qs.prefetch_related('burn_tests', 'retest_closures'):
            abnormal_types = self._get_sample_abnormal_types(s)
            abnormal_count = self._count_sample_abnormal(s)
            if not abnormal_types and abnormal_count == 0:
                continue
            latest = s.burn_tests.order_by('-test_time').first()
            has_closure = s.retest_closures.exists()
            is_closed = self._is_sample_closed(s)
            abnormal_samples.append({
                'id': s.id,
                'sample_code': s.sample_code,
                'test_batch': s.test_batch,
                'fragrance_code': s.fragrance_code,
                'cup_type': s.cup_type,
                'wick_spec': s.wick_spec,
                'responsible_person': s.responsible_person,
                'status': s.status,
                'status_display': s.get_status_display(),
                'abnormal_types': abnormal_types,
                'abnormal_count': abnormal_count,
                'latest_test_time': latest.test_time if latest else None,
                'retest_count': s.retest_count,
                'has_wick_alert': (s.test_batch, s.wick_spec) in alert_map,
                'has_closure': has_closure,
                'is_closed': is_closed,
            })

        abnormal_samples.sort(key=lambda x: (x['is_closed'], -x['abnormal_count']))

        page = self.paginator.paginate_queryset(abnormal_samples, request, view=self)
        if page is not None:
            serializer = ReviewAbnormalSampleSerializer(page, many=True)
            return self.paginator.get_paginated_response(serializer.data)
        serializer = ReviewAbnormalSampleSerializer(abnormal_samples, many=True)
        return Response({'count': len(abnormal_samples), 'results': serializer.data})


class ReviewWickRankingView(APIView, ReviewReportMixin):
    def get(self, request):
        samples_qs = self.get_filtered_samples(request)
        tests_qs = self.get_filtered_tests(samples_qs)
        limit = int(request.query_params.get('limit', 15))

        test_batch_set = set(samples_qs.values_list('test_batch', flat=True).distinct())
        wick_spec_set = set(samples_qs.values_list('wick_spec', flat=True).distinct())
        alert_map = set()
        for a in WickProblemAlert.objects.filter(
            resolved=False,
            test_batch__in=test_batch_set,
            wick_spec__in=wick_spec_set
        ):
            alert_map.add((a.test_batch, a.wick_spec))

        problem_tests = tests_qs.filter(
            Q(auto_flags__smoke_high=True) | Q(auto_flags__temp_high=True)
        )
        wick_problem_ids = problem_tests.values_list('wax_sample__wick_spec', 'wax_sample_id').distinct()
        wick_problem_map = {}
        for wick_spec, sample_id in wick_problem_ids:
            if wick_spec not in wick_problem_map:
                wick_problem_map[wick_spec] = set()
            wick_problem_map[wick_spec].add(sample_id)

        smoke_high_by_wick = {}
        for wick_spec, sample_id in tests_qs.filter(auto_flags__smoke_high=True).values_list(
            'wax_sample__wick_spec', 'wax_sample_id'
        ).distinct():
            smoke_high_by_wick.setdefault(wick_spec, set()).add(sample_id)

        temp_high_by_wick = {}
        for wick_spec, sample_id in tests_qs.filter(auto_flags__temp_high=True).values_list(
            'wax_sample__wick_spec', 'wax_sample_id'
        ).distinct():
            temp_high_by_wick.setdefault(wick_spec, set()).add(sample_id)

        total_flags_by_wick = {}
        for t in problem_tests.values('wax_sample__wick_spec').annotate(
            cnt=Count('id')
        ).order_by('-cnt'):
            total_flags_by_wick[t['wax_sample__wick_spec']] = t['cnt']

        wick_stats = []
        for wick_spec in wick_spec_set:
            total_samples = samples_qs.filter(wick_spec=wick_spec).count()
            problem_sample_ids = wick_problem_map.get(wick_spec, set())
            problem_sample_count = len(problem_sample_ids)
            if problem_sample_count == 0:
                continue
            problem_rate = round(problem_sample_count / total_samples * 100, 1) if total_samples > 0 else 0
            affected_samples = list(
                WaxSample.objects.filter(id__in=problem_sample_ids).values(
                    'id', 'sample_code', 'test_batch', 'fragrance_code', 'cup_type'
                )
            )
            has_unresolved = False
            for tb in test_batch_set:
                if (tb, wick_spec) in alert_map:
                    has_unresolved = True
                    break
            smoke_high_count = len(smoke_high_by_wick.get(wick_spec, set()))
            temp_high_count = len(temp_high_by_wick.get(wick_spec, set()))
            total_problem_flags = total_flags_by_wick.get(wick_spec, 0)
            wick_stats.append({
                'wick_spec': wick_spec,
                'total_samples': total_samples,
                'problem_sample_count': problem_sample_count,
                'problem_rate': problem_rate,
                'smoke_high_count': smoke_high_count,
                'temp_high_count': temp_high_count,
                'total_problem_flags': total_problem_flags,
                'affected_samples': affected_samples,
                'has_unresolved_alert': has_unresolved,
            })

        wick_stats.sort(key=lambda x: (-x['problem_sample_count'], -x['problem_rate']))
        wick_stats = wick_stats[:limit]

        serializer = ReviewWickRankingSerializer(wick_stats, many=True)
        return Response({'count': len(wick_stats), 'results': serializer.data})


class ReviewUnclosedListView(APIView, ReviewReportMixin):
    pagination_class = FlexiblePageNumberPagination

    @property
    def paginator(self):
        if not hasattr(self, '_paginator'):
            self._paginator = self.pagination_class()
        return self._paginator

    def get(self, request):
        samples_qs = self.get_filtered_samples(request)
        now = timezone.now()
        test_batch_set = set(samples_qs.values_list('test_batch', flat=True).distinct())
        wick_spec_set = set(samples_qs.values_list('wick_spec', flat=True).distinct())
        alert_map = set()
        for a in WickProblemAlert.objects.filter(
            resolved=False,
            test_batch__in=test_batch_set,
            wick_spec__in=wick_spec_set
        ):
            alert_map.add((a.test_batch, a.wick_spec))

        unclosed_items = []
        for s in samples_qs.prefetch_related('burn_tests', 'retest_closures', 'retest_plans').distinct():
            has_abnormal = False
            for t in s.burn_tests.all():
                flags = t.analyze_flags()
                if (flags.get('smoke_high') or flags.get('temp_high')
                        or flags.get('temp_low') or t.abnormal_desc):
                    has_abnormal = True
                    break
            if not has_abnormal:
                continue
            if self._is_sample_closed(s):
                continue

            latest = s.burn_tests.order_by('-test_time').first()
            latest_test_time = latest.test_time if latest else None
            days_since = None
            if latest_test_time:
                delta = now - latest_test_time
                days_since = delta.days

            abnormal_reason_parts = self._get_sample_abnormal_types(s)
            abnormal_reason = '、'.join(abnormal_reason_parts) if abnormal_reason_parts else '存在异常'

            retest_overdue = s.has_pending_retest_missing()

            latest_plan = s.retest_plans.order_by('-created_at').first()
            has_retest_plan = latest_plan is not None
            retest_plan_status = latest_plan.plan_status if latest_plan else None
            retest_plan_status_display = latest_plan.get_plan_status_display() if latest_plan else None
            planned_retest_time = latest_plan.planned_retest_time if latest_plan else None

            unclosed_items.append({
                'id': s.id,
                'sample_code': s.sample_code,
                'test_batch': s.test_batch,
                'fragrance_code': s.fragrance_code,
                'cup_type': s.cup_type,
                'wick_spec': s.wick_spec,
                'responsible_person': s.responsible_person,
                'status': s.status,
                'status_display': s.get_status_display(),
                'abnormal_reason': abnormal_reason,
                'latest_test_time': latest_test_time,
                'days_since_last_test': days_since,
                'retest_overdue': retest_overdue,
                'has_retest_plan': has_retest_plan,
                'retest_plan_status': retest_plan_status,
                'retest_plan_status_display': retest_plan_status_display,
                'planned_retest_time': planned_retest_time,
                'has_wick_alert': (s.test_batch, s.wick_spec) in alert_map,
            })

        def sort_key(x):
            priority = 0
            if x['retest_overdue']:
                priority += 4
            if x['has_wick_alert']:
                priority += 2
            if not x['has_retest_plan']:
                priority += 1
            days = x['days_since_last_test'] or 0
            return (-priority, -days)

        unclosed_items.sort(key=sort_key)

        page = self.paginator.paginate_queryset(unclosed_items, request, view=self)
        if page is not None:
            serializer = ReviewUnclosedItemSerializer(page, many=True)
            return self.paginator.get_paginated_response(serializer.data)
        serializer = ReviewUnclosedItemSerializer(unclosed_items, many=True)
        return Response({'count': len(unclosed_items), 'results': serializer.data})


class ReviewClosedRecordsView(APIView, ReviewReportMixin):
    pagination_class = FlexiblePageNumberPagination

    @property
    def paginator(self):
        if not hasattr(self, '_paginator'):
            self._paginator = self.pagination_class()
        return self._paginator

    def get(self, request):
        samples_qs = self.get_filtered_samples(request)
        closures_qs = RetestClosure.objects.filter(
            wax_sample__in=samples_qs,
            action__in=[ClosureActionChoices.CONFIRM_VERSION, ClosureActionChoices.TRANSFER_REFORM]
        ).select_related('wax_sample', 'burn_test').order_by('-created_at')

        records = []
        for c in closures_qs:
            s = c.wax_sample
            records.append({
                'closure_id': c.id,
                'sample_id': s.id,
                'sample_code': s.sample_code,
                'test_batch': s.test_batch,
                'fragrance_code': s.fragrance_code,
                'cup_type': s.cup_type,
                'wick_spec': s.wick_spec,
                'responsible_person': s.responsible_person,
                'action': c.action,
                'action_display': c.get_action_display(),
                'handler': c.handler,
                'remark': c.remark,
                'created_at': c.created_at,
                'burn_test_round': c.burn_test.test_round if c.burn_test else None,
            })

        page = self.paginator.paginate_queryset(records, request, view=self)
        if page is not None:
            serializer = ReviewClosedRecordSerializer(page, many=True)
            return self.paginator.get_paginated_response(serializer.data)
        serializer = ReviewClosedRecordSerializer(records, many=True)
        return Response({'count': len(records), 'results': serializer.data})


class ReviewSampleDetailView(APIView):
    def get(self, request, pk=None):
        try:
            sample = WaxSample.objects.select_related().prefetch_related(
                'burn_tests', 'retest_closures', 'retest_plans'
            ).get(pk=pk)
        except WaxSample.DoesNotExist:
            return Response({'error': '蜡样不存在'}, status=status.HTTP_404_NOT_FOUND)

        wick_alerts = WickProblemAlert.objects.filter(
            test_batch=sample.test_batch,
            wick_spec=sample.wick_spec
        ).order_by('-last_triggered')

        data = {
            'id': sample.id,
            'sample_code': sample.sample_code,
            'test_batch': sample.test_batch,
            'fragrance_code': sample.fragrance_code,
            'cup_type': sample.cup_type,
            'wick_spec': sample.wick_spec,
            'responsible_person': sample.responsible_person,
            'status': sample.status,
            'status_display': sample.get_status_display(),
            'created_at': sample.created_at,
            'updated_at': sample.updated_at,
            'remarks': sample.remarks or '',
            'retest_count': sample.retest_count,
            'wick_alerts': wick_alerts,
            'burn_tests': sample.burn_tests.order_by('test_time').all(),
            'retest_plans': sample.retest_plans.prefetch_related('executions').order_by('-created_at').all(),
            'closure_history': sample.retest_closures.order_by('-created_at').all(),
        }
        serializer = ReviewSampleDetailSerializer(data)
        return Response(serializer.data)


class ReviewReportOptionsView(APIView):
    def get(self, request):
        test_batches = list(
            WaxSample.objects.values_list('test_batch', flat=True).distinct().order_by('-test_batch')
        )
        fragrance_codes = list(
            WaxSample.objects.values_list('fragrance_code', flat=True).distinct().order_by('fragrance_code')
        )
        cup_types = list(
            WaxSample.objects.values_list('cup_type', flat=True).distinct().order_by('cup_type')
        )
        wick_specs = list(
            WaxSample.objects.values_list('wick_spec', flat=True).distinct().order_by('wick_spec')
        )
        responsible_persons = list(
            WaxSample.objects.values_list('responsible_person', flat=True).distinct().order_by('responsible_person')
        )

        status_options = [{'value': v, 'label': l} for v, l in StatusChoices.choices]
        abnormal_type_options = [
            {'value': 'smoke_high', 'label': '烟量偏高'},
            {'value': 'temp_high', 'label': '杯壁温度偏高'},
            {'value': 'temp_low', 'label': '杯壁温度偏低'},
            {'value': 'abnormal_desc', 'label': '人工异常描述'},
        ]
        processing_status_options = [
            {'value': 'unclosed', 'label': '未闭环'},
            {'value': 'closed', 'label': '已闭环'},
            {'value': 'has_closure', 'label': '有处理记录'},
            {'value': 'no_closure', 'label': '无处理记录'},
        ]

        return Response({
            'test_batches': test_batches,
            'fragrance_codes': fragrance_codes,
            'cup_types': cup_types,
            'wick_specs': wick_specs,
            'responsible_persons': responsible_persons,
            'status_options': StatusSerializer(status_options, many=True).data,
            'abnormal_type_options': AbnormalTypeSerializer(abnormal_type_options, many=True).data,
            'processing_status_options': ProcessingStatusSerializer(processing_status_options, many=True).data,
        })
