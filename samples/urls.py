from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    WaxSampleViewSet, BurnTestViewSet,
    ProblemWickRankingView, PendingRetestView, TestDurationDistributionView,
    health_check
)

router = DefaultRouter()
router.register(r'samples', WaxSampleViewSet, basename='wax-sample')
router.register(r'tests', BurnTestViewSet, basename='burn-test')

urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('', include(router.urls)),
    path('statistics/problem-wicks/', ProblemWickRankingView.as_view(), name='problem-wick-ranking'),
    path('statistics/pending-retests/', PendingRetestView.as_view(), name='pending-retests'),
    path('statistics/duration-distribution/', TestDurationDistributionView.as_view(), name='duration-distribution'),
]
