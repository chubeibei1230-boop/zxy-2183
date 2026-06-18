from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from samples.views import closure_dashboard, retest_plan_dashboard

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('samples.urls')),
    path('', lambda r: redirect('/retest-plan/dashboard/'), name='home'),
    path('closure/dashboard/', closure_dashboard, name='closure-dashboard-page'),
    path('retest-plan/dashboard/', retest_plan_dashboard, name='retest-plan-dashboard-page'),
]
