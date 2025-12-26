from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib import admin
from django.contrib.contenttypes.models import ContentType

# ----------------------------------------------------
# 1. TEMEL YAPILAR (Unit, Conversion, Helper Functions)
# ----------------------------------------------------

class Unit(models.Model):
    """Sistemde kullanılan tüm birimlerin (kg, adet, koli, vb.) ana tanımı."""
    name = models.CharField(max_length=50, unique=True, verbose_name="Birim Adı (Örn: kg, adet)")
    
    def __str__(self):
        return self.name
        
    class Meta:
        verbose_name = "Tanımlı Birim"
        verbose_name_plural = "05.Birim Tanımları"

# ----------------------------------------------------------------------
# BİRİM ÇEVRİM YARDIMCI FONKSİYONU
# ----------------------------------------------------------------------

def convert_unit(quantity, source_unit, target_unit):
    """Miktarı, kaynak birimden hedef birime çevirir. Unit objesi alır."""
    from .models import UnitConversion # Model importu fonk. içine taşındı
    
    # 1. Miktar Decimal değilse Decimal'e çevir
    try:
        quantity = Decimal(str(quantity))
    except:
        return Decimal('0.00') # Miktar okunamıyorsa 0 dön
        
    # 2. Birimler aynıysa çevrim yapma
    if source_unit == target_unit:
        return quantity
    
    # 3. Çevrim Tanımlamasını Ara
    try:
        # Doğrudan çevrim var mı? (A -> B)
        conversion = UnitConversion.objects.get(
            source_unit=source_unit,
            target_unit=target_unit
        )
        factor = Decimal(str(conversion.conversion_factor))
        
        # Çevrim faktörü 0 ise bölme hatasını engelle
        if factor == Decimal('0.00'):
            return quantity 

        return quantity * factor
    
    except UnitConversion.DoesNotExist:
        try:
            # Ters çevrim var mı? (B -> A)
            conversion = UnitConversion.objects.get(
                source_unit=target_unit,
                target_unit=source_unit
            )
            factor = Decimal(str(conversion.conversion_factor))

            # Çevrim faktörü 0 ise ZeroDivisionError hatasını engelle
            if factor == Decimal('0.00'):
                return quantity
                
            return quantity / factor
            
        except UnitConversion.DoesNotExist:
            # KRİTİK: Çevrim yoksa, HATA VERMELİ veya bu kalemi atlamalıyız.
            # Hesaplama sırasında 0 dönmek, toplam maliyeti sıfırlar.
            # Veri kaybetmemek adına, çevrim yoksa miktarı olduğu gibi bırakalım (1 çarpanı gibi).
            # ANCAK bu, hatalı sonuç verebilir. En güvenlisi 0 dönmektir, ama madem 0 istenmiyor:
            return Decimal('0.00') 

    except Exception:
        # Diğer hatalar (örneğin Decimal çevrim hatası)
        return Decimal('0.00')

class UnitConversion(models.Model):
    source_unit = models.ForeignKey(Unit, related_name='source_conversions', on_delete=models.CASCADE, verbose_name="Kaynak Birim")
    target_unit = models.ForeignKey(Unit, related_name='target_conversions', on_delete=models.CASCADE, verbose_name="Hedef Birim")
    conversion_factor = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        verbose_name="Çevrim Faktörü (Kaynak * Faktör = Hedef)",
        help_text="Örn: 1 kg'ı 1000 gr'a çevirmek için 1000 girin. 1 gr'ı 1 kg'a çevirmek için 0.001 girin."
    )
    
    class Meta:
        unique_together = ('source_unit', 'target_unit')
        verbose_name = "Birim Çevrimi" # Eklendi
        verbose_name_plural = "06.Birim Çevrimleri" # Eklendi

    def __str__(self):
        return f"1 {self.source_unit.name} = {self.conversion_factor} {self.target_unit.name}"


# ----------------------------------------------------
# 2. KULLANICI VE ROL İLİŞKİLERİ
# ----------------------------------------------------

class Dealer(models.Model):
    """Bayi Kaydı ve Cari Hesap Bilgisi (Müşteri)"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='dealer_profile', verbose_name="Kullanıcı")
    name = models.CharField(max_length=100, verbose_name="Bayi Adı/Unvanı")
    tax_id = models.CharField(max_length=20, unique=True, verbose_name="Vergi Numarası")
    current_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Cari Bakiye")

    # Bayinin tüm cari hareketlerini (transaction) çeken metod
    @property
    def get_transactions(self):
        # Transaction modelinin dealer'a ForeignKey ile bağlı olduğunu varsayıyorum.
        # En yeni hareket en üstte olacak şekilde sırala
        return self.transaction_set.all().order_by('-date')


    class Meta:
        verbose_name = "Bayi Hesap"
        verbose_name_plural = "02. Bayi Hesapları"

    def __str__(self):
        return self.name

class Courier(models.Model):
    """Kurye Kaydı (Mobil Uygulama Kullanıcısı)"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='courier_profile', verbose_name="Kullanıcı")
    name = models.CharField(max_length=100, verbose_name="Kurye Adı")

    class Meta:
        verbose_name = "Kurye"
        verbose_name_plural = "12.Kuryeler"

    def __str__(self):
        return self.name

class Transaction(models.Model):
    """Bayi cari hesap hareketlerini (borç/alacak) tutar."""
    TYPE_CHOICES = [
        ('DEBT', 'Borç (Satış/Fatura)'),
        ('COLLECTION', 'Alacak (Tahsilat)')
    ]
    
    dealer = models.ForeignKey(
        'Dealer', 
        on_delete=models.PROTECT, 
        related_name='transactions', 
        verbose_name="Bayi"
    )
    
    transaction_type = models.CharField(
        max_length=10, 
        choices=TYPE_CHOICES, 
        verbose_name="Hareket Türü"
    )
    amount = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="Miktar"
    )
    transaction_date = models.DateTimeField(
        auto_now_add=True, 
        verbose_name="Tarih"
    )
    source_model = models.CharField(
        max_length=30, 
        null=True, 
        blank=True
    )

    source_id = models.IntegerField(
        null=True, 
        blank=True
    )
 
    class Meta:
        verbose_name = "Cari Hesap Hareketi"
        verbose_name_plural = "04. Hesap Hareketleri"


# ----------------------------------------------------
# 3. ÜRÜN VE ENVANTER
# ----------------------------------------------------
# management/models.py
class Product(models.Model):
    # ... (mevcut alanlar) ...
    # KRİTİK EKLENTİ
    current_stock = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'), 
        verbose_name="Mevcut Stok Miktarı"
    )



class Product(models.Model):
    """Satılan Ürünlerin Bilgileri (A. Ürün Yönetimi)"""
    name = models.CharField(max_length=255, verbose_name="Ürün Adı")
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Satış Fiyatı")
    is_active = models.BooleanField(default=True, verbose_name="Aktif Satışta mı?")

    # Satış Birimi (Unit modeline Foreign Key)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, verbose_name="Ana Birim")
    
    vat_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.20'), 
        verbose_name="Satış KDV Oranı (Decimal)",
        help_text="Örnek: %20 için 0.20, %10 için 0.10 giriniz."
    )
    
    price_vat_included = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'),
        verbose_name="Satış Fiyatı (KDV Dahil)"
    )

    class Meta:
        verbose_name = "Ürün"
        verbose_name_plural = "07.Ürünler"

    def __str__(self):
        return f"{self.name} ({self.selling_price} TL)"


# ----------------------------------------------------
# 4. SİPARİŞ VE TESLİMAT AKIŞI
# ----------------------------------------------------

class Order(models.Model):
    is_locked = models.BooleanField(default=False, verbose_name="Fiyat/Durum Kilitli")
    STATUS_CHOICES = [
        ('NEW', 'Yeni Sipariş'),
        ('PREP', 'Hazırlanıyor'),
        ('DELIVERY', 'Teslimatta'),
        ('CONFIRMED', 'Teslim Edildi/Tamamlandı'),
        ('INVOICED', 'Faturalandırıldı'),
        ('CANCELED', 'İptal Edildi'),
    ]
    status = models.CharField(max_length=20, default='PENDING', verbose_name="Sipariş Durumu")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='NEW', verbose_name="Durum")
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, related_name='orders', verbose_name="Bayi")
    order_date = models.DateTimeField(default=timezone.now, verbose_name="Sipariş Tarihi")
    estimated_total = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Tahmini Toplam Tutar")
   
    class Meta:
        verbose_name = "Sipariş"
        verbose_name_plural = "10.Siparişler"

    def save(self, *args, **kwargs):
        ignore_lock = kwargs.pop('ignore_lock', False) 
        
        if self.pk and self.is_locked and not ignore_lock:
            try:
                original = Order.objects.get(pk=self.pk)
                if original.status != self.status:
                     self.status = original.status 
            except Order.DoesNotExist:
                pass 

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Sipariş #{self.id} - {self.dealer.name}"

class OrderItem(models.Model):
    """Bir Siparişe Ait Ürün Kalemleri (Birim Çevrimini Kullanır)"""
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items', verbose_name="Sipariş")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name="Ürün")
    
    # KRİTİK DÜZELTME: Ondalıklı miktar için DecimalField kullanıldı
    ordered_quantity = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Sipariş Edilen Miktar")
    
    # Sipariş edilen birim (Unit modeline Foreign Key)
    ordered_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, verbose_name="Sipariş Birimi") 
    
    # Ürün ana birimi cinsinden birim fiyatı tutar
    unit_price_at_order = models.DecimalField(
        max_digits=10, 
        decimal_places=4, 
        null=True, 
        blank=True, 
        verbose_name="Sipariş Anındaki Birim Fiyat (Ürün Ana Birimi Cinsinden)"
    )

    class Meta:
        verbose_name = "Sipariş Kalemi"
        verbose_name_plural = "Sipariş Kalemleri"

    def __str__(self):
        return f"{self.product.name} ({self.ordered_quantity} {self.ordered_unit.name})"
    
    # KRİTİK: Birim çevrimi ile toplam tutarı hesaplayan metot
    def get_converted_total(self):
        """
        Sipariş miktarını ürünün fiyatının tanımlandığı birime çevirerek 
        doğru toplam tutarı hesaplar.
        """
        if not self.product or not self.unit_price_at_order or not self.product.unit:
            return Decimal('0.00')

        # 1. Sipariş edilen miktarı, ürünün fiyat birimine (Product.unit) çevir.
        converted_quantity = convert_unit(
            self.ordered_quantity,
            self.ordered_unit,          # Kaynak: Unit objesi
            self.product.unit           # Hedef: Unit objesi
        )
        
        return converted_quantity * self.unit_price_at_order

    # KRİTİK: Yanlış yere konulmuş metotlar buraya geri taşındı ve düzeltildi.
    @property
    @admin.display(description='Toplam Fiyat (Birim Fiyat * Çevrimli Miktar)')
    def total_price(self):
        """Sipariş edilen miktar * Birim Fiyat hesaplaması (Çevrimli)."""
        return self.get_converted_total()
    
    @property
    @admin.display(description='Tahmini Toplam')
    def estimated_total(self):
        """Tahmini toplamı döndürür."""
        return self.get_converted_total()
    
    def line_total(self):
        """Bu kalem için toplam tutarı hesaplar (Çevrimli)"""
        return self.get_converted_total()
    line_total.short_description = "Alt Toplam (TL)" 

class Delivery(models.Model):
    """Teslimat ve Onay Kaydı"""
    order_item = models.OneToOneField(OrderItem, on_delete=models.CASCADE, related_name='delivery', verbose_name="Sipariş Kalemi")
    
    courier = models.ForeignKey(
        Courier,
        on_delete=models.SET_NULL, 
        null=True,                 
        blank=True,                
        related_name='deliveries', 
        verbose_name="Kurye"
        )
    
    delivered_quantity = models.PositiveIntegerField(default=0, verbose_name="Teslim Edilen Miktar")
    is_confirmed = models.BooleanField(default=False, verbose_name="Teslimat Onaylandı mı?")
    delivery_date = models.DateTimeField(null=True, blank=True, verbose_name="Teslimat Tarihi")

    class Meta:
        verbose_name = "Teslimat Kaydı"
        verbose_name_plural = "12.Kurye Teslimat Kayıtları"

    def __str__(self):
        return f"Teslimat ID:{self.id} - {self.order_item.product.name}"

# ----------------------------------------------------
# 5. FATURA
# ----------------------------------------------------
class Invoice(models.Model):
    """Resmi Fatura Kaydı"""
    
    invoice_number = models.CharField(max_length=50, unique=True, verbose_name="Fatura Numarası")
    order = models.OneToOneField('Order', on_delete=models.CASCADE, related_name='invoice', verbose_name="Sipariş")
    dealer = models.ForeignKey('Dealer', on_delete=models.PROTECT, related_name='invoices', verbose_name="Bayi")
    invoice_date = models.DateTimeField(default=timezone.now, verbose_name="Fatura Tarihi")
    final_amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Nihai Tutar")

    class Meta:
        verbose_name = "Fatura"
        verbose_name_plural = "14.Faturalar"
        ordering = ['-invoice_date', 'invoice_number']
        
    def __str__(self):
        return f"Fatura #{self.invoice_number} - {self.dealer.name}"


# ----------------------------------------------------
# 6. FİNANSAL TAKİP
# ----------------------------------------------------
class Expense(models.Model):
    """Genel Gider Kayıtları"""
    CATEGORY_CHOICES = [
        ('RENT', 'Kira'),
        ('SALARY', 'Maaş'),
        ('RAW', 'Hammadde'),
        ('OTHER', 'Diğer'),
    ]
    name = models.CharField(max_length=100, verbose_name="Gider Adı")
    category = models.CharField(max_length=10, choices=CATEGORY_CHOICES, verbose_name="Kategori")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Tutar")
    date = models.DateField(default=timezone.now, verbose_name="Tarih")
    
    class Meta:
        verbose_name = "Gider"
        verbose_name_plural = "15.Giderler"

class Collection(models.Model):
    """Tahsilat Giriş Kayıtları"""
    METHOD_CHOICES = [
        ('CASH', 'Nakit'),
        ('BANK', 'Banka Havalesi'),
        ('CARD', 'Kredi Kartı'),
    ]
    dealer = models.ForeignKey(Dealer, on_delete=models.PROTECT, related_name='collections', verbose_name="Bayi")
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="Tutar")
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default='CASH', verbose_name="Ödeme Yöntemi")
    collection_date = models.DateTimeField(default=timezone.now, verbose_name="İşlem Tarihi")

    def save(self, *args, **kwargs):
        is_new = not self.pk
        
        if is_new:
            # 1. Borcu DÜŞÜR
            self.dealer.current_balance -= self.amount
            self.dealer.save()

            # 2. Cari Hesap Hareketi (Transaction) Oluştur
            # GFK için ContentType objesini alıyoruz
            collection_type = ContentType.objects.get_for_model(self) 
            
            Transaction.objects.create(
                dealer=self.dealer,
                amount=-self.amount, 
                transaction_type='COLLECTION', 
                transaction_date=self.collection_date,
                
                # KRİTİK DÜZELTME: Generic Foreign Key alanlarını doldur
                source_model=collection_type, # Hangi model olduğunu belirtir (ContentType)
                source_id=self.pk            # Kayıt ID'sini belirtir
            )
            
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # 1. Bakiye Düzeltmesi: Silme işlemi borcu tekrar artırmalı (ters işlem)
        self.dealer.current_balance += self.amount
        self.dealer.save()

        # 2. Cari Hesap Hareketini Sil
        # Transaction.objects.filter(source_collection=self).delete() # source_collection FK'sı varsa
        
        super().delete(*args, **kwargs)



    class Meta:
        verbose_name = "Tahsilat"
        verbose_name_plural = "04.Tahsilatlar"


class Partner(models.Model):
    """Ortak ve kâr dağıtım oranını tutar."""
    user = models.OneToOneField(
        User, 
        on_delete=models.CASCADE, 
        related_name='partner_profile', 
        verbose_name="Kullanıcı",
        
        # BU İKİ AYAR KESİNLİKLE OLMALI
        null=True,  
        blank=True  
    )
    name = models.CharField(max_length=100, verbose_name="Ortak Adı")
    share_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('0.00'), 
        verbose_name="Kar Payı Yüzdesi (%)" 
    )
    total_profit_received = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=Decimal('0.00'), 
        verbose_name="Alınan Toplam Kar Payı"
    )
    current_receivable = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0.00, 
        verbose_name="Alacak Bakiyesi"
    )

    distribution_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Dağıtım Oranı (%)" 
    )
    
    def __str__(self):
        if self.user:
            # Eğer user varsa, adını kullan (get_full_name veya username)
            return f"{self.user.get_full_name() or self.user.username} (Oran: {self.distribution_ratio}%)"
        # Eğer user atanmamışsa, Partner'ın kendi adını kullan
        return f"{self.name} (Kullanıcı Atanmamış)"

    class Meta:
        verbose_name = "Ortak"
        verbose_name_plural = "80. Ortaklar ve Oranları"

# YENİ MODEL: Partnerlerin o aydan aldığı payı tutacak
class PartnerProfitShare(models.Model):
    """Belirli bir ay için ortağın kâr payı detaylarını tutar."""
    distribution = models.ForeignKey(
        'ProfitDistribution', 
        on_delete=models.CASCADE, 
        related_name='shares', 
        verbose_name="Kâr Dağıtım Kaydı"
    )
    partner = models.ForeignKey(
        'Partner', 
        on_delete=models.PROTECT, # Ortak silinirse payları koru
        verbose_name="Ortak"
    )
    share_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name="Kullanılan Oran (%)"
    )
    calculated_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Hesaplanan Tutar (TL)"
    )

    def __str__(self):
        return f"{self.distribution.month}/{self.distribution.year} - {self.partner.user.username}: {self.calculated_amount} TL"

    class Meta:
        verbose_name = "Ortak Kâr Payı"
        verbose_name_plural = "Ortak Kâr Payları"
        # Bir ortak, aynı dağıtım kaydında sadece bir kez yer alabilir
        unique_together = ('distribution', 'partner')


class ProfitDistribution(models.Model):
    # KRİTİK EKLENTİLER: admin.py'nin referans verdiği alanlar
    month = models.IntegerField(
        verbose_name="Ay",
        choices=[(i, str(i)) for i in range(1, 13)] # 1'den 12'ye kadar seçim
    )
    year = models.IntegerField(
        verbose_name="Yıl",
        default=timezone.now().year # Varsayılan olarak geçerli yıl
    )
    
    total_net_profit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal('0.00'),
        verbose_name="Toplam Net Kâr"
    )
    
    is_distributed = models.BooleanField(
        default=False,
        verbose_name="Kâr Dağıtımı Yapıldı mı?"
    )
    
    description = models.TextField(
        blank=True,
        verbose_name="Dağıtım Açıklaması"
    )

    def __str__(self):
        return f"Kâr Dağıtımı: {self.month}/{self.year} ({self.total_net_profit} TL)"

    class Meta:
        verbose_name = "Kâr Dağıtımı"
        verbose_name_plural = "90. Kâr Dağıtımı Yönetimi"
        unique_together = ('month', 'year') # Bir ay için sadece bir kayıt olabilir
# ----------------------------------------------------
# 7. REÇETE VE HAMMADDE
# ----------------------------------------------------

class RawMaterial(models.Model):
    """Ürünlerin üretimi için kullanılan Hammadde/Bileşenler."""
    name = models.CharField(max_length=255, verbose_name="Hammadde Adı")
    # Maliyet Birimi (Unit modeline Foreign Key)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, verbose_name="Maliyet Birimi")
    cost_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        default=0, 
        verbose_name="Birim Alış Maliyeti"
    )
    is_active = models.BooleanField(default=True, verbose_name="Aktif")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "Hammadde"
        verbose_name_plural = "08.Hammaddeler"


class Recipe(models.Model):
    """Bir nihai ürünün nasıl üretileceğini tanımlayan ana reçete."""
    product = models.OneToOneField(
        'Product', 
        on_delete=models.CASCADE, 
        related_name='recipe', 
        verbose_name="Nihai Ürün"
    )
    description = models.TextField(blank=True, null=True, verbose_name="Açıklama/Hazırlık Notları")
    is_active = models.BooleanField(default=True, verbose_name="Aktif Reçete")

    def __str__(self):
        return f"{self.product.name} Reçetesi"

    def calculate_total_cost(self):
        total_cost = Decimal('0.00')
        
        # 1. Reçete için temel birimi al
        try:
            # self.product.unit'e erişim (Model Yüklenmesi hatası almamak için)
            recipe_base_unit = self.product.unit 
            if not recipe_base_unit:
                return Decimal('0.00')
        except AttributeError:
            return Decimal('0.00') 

        # 2. Reçete kalemlerini döngüye al
        for item in self.recipeitem_set.select_related('raw_material__unit').all():
            
            raw_material = item.raw_material
            
            # Gerekli tüm alanların dolu ve geçerli olduğundan emin ol
            if not (raw_material and 
                    raw_material.cost_price is not None and 
                    item.quantity_required is not None and 
                    raw_material.unit):
                continue

            try:
                raw_material_unit = raw_material.unit      # Hammadde Maliyet Birimi
                required_qty = Decimal(str(item.quantity_required))
                cost_price = Decimal(str(raw_material.cost_price))
                
                # 3. Birim Çevrimi
                # ÖNEMLİ: Eğer convert_unit'in içinde Unit objesi yerine string kullanıyorsanız:
                # convert_unit(required_qty, recipe_base_unit.name, raw_material_unit.name)
                # Ancak varsayılan olarak Unit objeleri gönderiyoruz.
                converted_qty = convert_unit(
                    required_qty,
                    recipe_base_unit,      
                    raw_material_unit      
                )
                
                # Eğer çevrim başarısız olursa ve 0 dönerse (convert_unit içinde kural yoksa)
                if converted_qty == Decimal('0.00'):
                    # Bu noktada, veri hatası veya çevrim tanımı eksikliği var demektir.
                    # Hata vermemek için bu kalemi atla.
                    continue

                # 4. Maliyeti Hesapla
                item_cost = converted_qty * cost_price
                total_cost += item_cost
                
            except Exception:
                continue
        
        # Sonucu 2 ondalık basamağa yuvarlayarak dön
        return total_cost.quantize(Decimal('0.01'))
    

    class Meta:
        verbose_name = "Ürün Reçetesi"
        verbose_name_plural = "09.Ürün Reçeteleri"


class RecipeItem(models.Model):
    """Bir reçeteyi oluşturan Hammadde ve gerekli miktar bilgisi."""
    recipe = models.ForeignKey(
        Recipe, 
        on_delete=models.CASCADE, 
        related_name='items',
        verbose_name="Reçete"
    )
    raw_material = models.ForeignKey(
        RawMaterial, 
        on_delete=models.CASCADE,
        verbose_name="Hammadde"
    )
    quantity_required = models.DecimalField(
        max_digits=10, 
        decimal_places=4, 
        verbose_name="Gerekli Miktar"
    )
    
    def __str__(self):
        return f"{self.recipe.product.name} için {self.raw_material.name}"

    class Meta:
        verbose_name = "Reçete Kalemi"
        verbose_name_plural = "Reçete Kalemleri"
        unique_together = ('recipe', 'raw_material')

# ----------------------------------------------------
# 8. YARDIMCI MODELLER
# ----------------------------------------------------

class DealerPrice(models.Model):
    """Bayiye özel ürün satış fiyatlarını tutar."""
    dealer = models.ForeignKey(
        'Dealer', 
        on_delete=models.CASCADE, 
        related_name='prices', 
        verbose_name="Bayi"
    )
    product = models.ForeignKey(
        'Product', 
        on_delete=models.CASCADE, 
        related_name='dealer_prices', 
        verbose_name="Ürün"
    )
    price = models.DecimalField(
        max_digits=10, 
        decimal_places=2, 
        verbose_name="Bayiye Özel Satış Fiyatı"
    )

    def __str__(self):
        return f"{self.dealer.name} için {self.product.name} ({self.price} TL)"

    class Meta:
        verbose_name = "Bayi Özel Fiyatı"
        verbose_name_plural = "04.Bayi Satış Fiyat Tanımlama"
        unique_together = ('dealer', 'product')

class OrderConfiguration(models.Model):
    """Admin'in global sipariş alım durumunu yönetebileceği tekil ayar modeli."""
    is_ordering_enabled = models.BooleanField(
        default=True, 
        verbose_name="Bayi Sipariş Alımı Açık mı?"
    )
    
    class Meta:
        verbose_name = "Global Sipariş Ayarı"
        verbose_name_plural = "10.Sipariş Kontrol"
    
    def __str__(self):
        return "Global Sipariş Ayarları"