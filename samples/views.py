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
    PlanSummarySerializer
)
from .filters import WaxSampleFilter, BurnTestFilter, ClosureSampleFilter, RetestClosureFilter, RetestPlanFilter, RetestPlanExecutionFilter


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
