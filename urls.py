from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    
    path('management-app/', include('management.urls', namespace='management')),
    # Tüm proje API'leri '/api/' yolu altında toplanır
    path('api/', include('management.urls')),
    
    # Auth için DRF'nin varsayılan login/logout endpoint'lerini ekleyebiliriz (Geliştirme için)
    # path('api-auth/', include('rest_framework.urls')),
]