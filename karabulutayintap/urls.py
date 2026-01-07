from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static


urlpatterns = [
    path('admin/', admin.site.urls),
    path('management/', include('management.urls')), # 'management/' ön eki burada tanımlı olmalı
    path('accounts/', include('django.contrib.auth.urls')),
    path('', include('management.urls'))
]

# Localde statik dosyaları görmek için bu blok ŞARTTIR:
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)