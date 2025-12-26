# management/permissions.py

from rest_framework import permissions
from .models import Dealer, Courier
from django.contrib.auth.models import Group

# Grup adlarını settings.py'de tanımlamak daha iyidir, ancak basitlik için burada tanımlayalım
ADMIN_GROUP = "Admin"
PARTNER_GROUP = "Partner"

def is_admin_user(user):
    """Kullanıcının 'Admin' grubunda olup olmadığını kontrol eder."""
    return user.groups.filter(name=ADMIN_GROUP).exists()

def is_dealer_user(user):
    """Kullanıcının bir Bayi (Dealer) objesi ile ilişkili olup olmadığını kontrol eder."""
    try:
        return Dealer.objects.filter(user=user).exists()
    except:
        return False

def is_courier_user(user):
    """Kullanıcının bir Kurye (Courier) objesi ile ilişkili olup olmadığını kontrol eder."""
    try:
        return Courier.objects.filter(user=user).exists()
    except:
        return False
        
def is_partner_user(user):
    """Kullanıcının bir Ortak (Partner) grubunda olup olmadığını kontrol eder."""
    return user.groups.filter(name=PARTNER_GROUP).exists()

class IsAdminUser(permissions.BasePermission):
    """Sadece Yönetici (Admin) grubundaki kullanıcıların erişimine izin verir."""
    message = "Bu işleme sadece Yönetici yetkisine sahip kullanıcılar erişebilir."

    def has_permission(self, request, view):
        # Sadece Admin rolüne sahip kullanıcılar izin alır
        return is_admin_user(request.user)

class IsDealerUser(permissions.BasePermission):
    """Sadece Bayi (Dealer) rolüne sahip kullanıcıların erişimine izin verir."""
    message = "Bu işleme sadece Bayi yetkisine sahip kullanıcılar erişebilir."

    def has_permission(self, request, view):
        # Sadece Bayi objesi ile ilişkilendirilmiş kullanıcılar izin alır
        return is_dealer_user(request.user)
    
class IsManagerOrReadOnly(permissions.BasePermission):
    """
    Kullanıcının yönetici (is_staff) olmasını veya isteğin güvenli (GET, HEAD, OPTIONS) olmasını zorunlu kılar.
    Güvenli olmayan (POST, PUT, DELETE) istekleri sadece yöneticiler yapabilir.
    """
    def has_permission(self, request, view):
        # GET, HEAD, OPTIONS isteklerine her zaman izin ver (listeleme/görüntüleme)
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Güvenli olmayan (POST, PUT, PATCH, DELETE) isteklere sadece Yönetici (Admin) izin verir
        # Bu, is_staff veya is_superuser olan kullanıcıları kapsar.
        return request.user and request.user.is_staff

class IsCourierUser(permissions.BasePermission):
    """Sadece Kurye (Courier) rolüne sahip kullanıcıların erişimine izin verir."""
    message = "Bu işleme sadece Kurye yetkisine sahip kullanıcılar erişebilir."

    def has_permission(self, request, view):
        # Sadece Kurye objesi ile ilişkilendirilmiş kullanıcılar izin alır
        return is_courier_user(request.user)
        
class IsPartnerUser(permissions.BasePermission):
    """Sadece Ortak (Partner) rolüne sahip kullanıcıların erişimine izin verir."""
    message = "Bu işleme sadece Ortak yetkisine sahip kullanıcılar erişebilir."

    def has_permission(self, request, view):
        # Sadece Partner grubundaki kullanıcılar izin alır
        return is_partner_user(request.user)
    
class OrderPermissions(permissions.BasePermission):
    """
    Sipariş detayları için kapsamlı izin sınıfı:
    1. Yönetici: Her zaman tüm işlemleri yapabilir.
    2. Bayi: Sadece kendi siparişini görebilir.
    3. Bayi: Sadece durumu 'NEW' olan siparişleri güncelleyebilir/silebilir.
    """

    def has_object_permission(self, request, view, obj):
        user = request.user

        # 1. Yönetici Kontrolü: Yönetici (is_staff) her zaman tam yetkilidir.
        if user.is_staff:
            return True

        # 2. Bayi Rolü Kontrolü
        if user.groups.filter(name='Bayi').exists():
            # A. Sahiplik Kontrolü
            try:
                dealer = Dealer.objects.get(user=user)
                is_owner = obj.dealer == dealer
            except Dealer.DoesNotExist:
                return False # Geçerli bir bayi kullanıcısı değil

            if is_owner:
                # B. Okuma Erişimi (GET, HEAD, OPTIONS): Sahibi her zaman görebilir.
                if request.method in permissions.SAFE_METHODS:
                    return True

                # C. Yazma Erişimi (PUT, PATCH, DELETE): Yalnızca 'NEW' durumunda
                if request.method in ('PUT', 'PATCH', 'DELETE'):
                    # KRİTİK KURAL: Sipariş durumu 'NEW' ise izin ver.
                    return obj.status == 'NEW'
                
                return False # Diğer güvensiz metodlara izin verme

            return False # Sahibi değilse izin verme
        
        # Diğer tüm durumlar için (Örn: Kurye, kimlik doğrulaması yapılmamış) erişimi reddet
        return False