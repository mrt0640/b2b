from django.apps import AppConfig


class ManagementConfig(AppConfig):
    name = 'management'
    verbose_name = 'Yönetim Uygulaması' 
    default_auto_field = 'django.db.models.BigAutoField'
    
    #def ready(self):
     #   import management.models  # Sinyallerin yüklendiğinden emin oluyoruz
