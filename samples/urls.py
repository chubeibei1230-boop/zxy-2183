from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    WaxSampleViewSet, BurnTestViewSet, WickProblemAlertViewSet,
    ProblemWickRankingView, PendingRetestView, TestDurationDistributionView,
    RetestClosureViewSet, ClosureSampleViewSet, ClosureSummaryView,
    RetestPlanViewSet, RetestPlanExecutionViewSet,
    health_check, closure_dashboard, retest_plan_dashboard, review_report_dashboard,
    ReviewReportSummaryView, ReviewAbnormalSampleListView, ReviewWickRankingView,
    ReviewUnclosedListView, ReviewClosedRecordsView, ReviewSampleDetailView,
    ReviewReportOptionsView
)

router = DefaultRouter()
router.register(r'samples', WaxSampleViewSet, basename='wax-sample')
router.register(r'tests', BurnTestViewSet, basename='burn-test')
router.register(r'wick-alerts', WickProblemAlertViewSet, basename='wick-alert')
router.register(r'retest-closures', RetestClosureViewSet, basename='retest-closure')
router.register(r'closure-samples', ClosureSampleViewSet, basename='closure-sample')
router.register(r'retest-plans', RetestPlanViewSet, basename='retest-plan')
router.register(r'plan-executions', RetestPlanExecutionViewSet, basename='plan-execution')

urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('', include(router.urls)),
    path('statistics/problem-wicks/', ProblemWickRankingView.as_view(), name='problem-wick-ranking'),
    path('statistics/pending-retests/', PendingRetestView.as_view(), name='pending-retests'),
    path('statistics/duration-distribution/', TestDurationDistributionView.as_view(), name='duration-distribution'),
    path('closure/summary/', ClosureSummaryView.as_view(), name='closure-summary'),
    path('closure/dashboard/', closure_dashboard, name='closure-dashboard'),
    path('retest-plan/dashboard/', retest_plan_dashboard, name='retest-plan-dashboard'),
    path('review/options/', ReviewReportOptionsView.as_view(), name='review-options'),
    path('review/summary/', ReviewReportSummaryView.as_view(), name='review-summary'),
    path('review/abnormal-samples/', ReviewAbnormalSampleListView.as_view(), name='review-abnormal-samples'),
    path('review/wick-ranking/', ReviewWickRankingView.as_view(), name='review-wick-ranking'),
    path('review/unclosed/', ReviewUnclosedListView.as_view(), name='review-unclosed'),
    path('review/closed-records/', ReviewClosedRecordsView.as_view(), name='review-closed-records'),
    path('review/sample-detail/<int:pk>/', ReviewSampleDetailView.as_view(), name='review-sample-detail'),
    path('review/dashboard/', review_report_dashboard, name='review-dashboard'),
]
