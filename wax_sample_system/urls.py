from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from samples.views import closure_dashboard

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('samples.urls')),
    path('', lambda r: redirect('/closure/dashboard/'), name='home'),
    path('closure/dashboard/', closure_dashboard, name='closure-dashboard-page'),
]
