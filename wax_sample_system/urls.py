from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from samples.views import closure_dashboard, retest_plan_dashboard, review_report_dashboard

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('samples.urls')),
    path('', lambda r: redirect('/review/dashboard/'), name='home'),
    path('closure/dashboard/', closure_dashboard, name='closure-dashboard-page'),
    path('retest-plan/dashboard/', retest_plan_dashboard, name='retest-plan-dashboard-page'),
    path('review/dashboard/', review_report_dashboard, name='review-dashboard-page'),
]
