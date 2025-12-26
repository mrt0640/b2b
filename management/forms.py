from django import forms
from .models import Order, OrderItem, Product, Dealer, Delivery, Courier, Unit
from django.forms.widgets import HiddenInput # HiddenInput'ı import edin
from django.forms import inlineformset_factory
# 1. Sipariş Ana (Header) Formu
class OrderForm(forms.ModelForm):
    # Teslimat Tarihi alanını HTML5 date input olarak kullanmak için
    delivery_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    
    # Siparişle ilgili ek notlar için özel alan
    notes = forms.CharField(
        required=False, 
        widget=forms.Textarea(attrs={'class': 'form-control', 'rows': 3})
    )

    class Meta:
        model = Order
        # Bayi (dealer) ve Toplam tutar (total_amount) gibi alanlar otomatik olarak 
        # view içinde ayarlanacağı için, formda görünmelerine gerek yok.
        fields = ['delivery_date', 'notes'] 
        
        # Eğer Order modelinizde 'status' alanı varsa ve formda görünmesini istemiyorsanız:
        # exclude = ['dealer', 'total_amount', 'status'] 
        
        # Bootstrap uyumlu CSS sınıfları ekleyelim
        widgets = {
            'delivery_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            # Bu, fields içinde tanımlı delivery_date'i geçersiz kılmaz.
            # widgets'ı sadece formda görünmesini istediğimiz diğer alanlar için kullanabiliriz.
            # Örneğin:
            # 'order_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        }


# 2. Sipariş Kalemi (Item) Formu
# Bu form Seti (FormSet) ile birden fazla kez kullanılacaktır.
class OrderItemForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = ['product', 'ordered_quantity', 'ordered_unit', 'unit_price_at_order']
        widgets = {
            # JS'in tanıması için 'select-product' class'ı eklendi
            'product': forms.Select(attrs={'class': 'form-select select-product'}),
            'ordered_quantity': forms.NumberInput(attrs={'class': 'form-control quantity-input', 'step': '0.01'}),
            # JS'in tanıması için 'select-unit' class'ı eklendi
            'ordered_unit': forms.Select(attrs={'class': 'form-select select-unit'}),
            # KRİTİK: AJAX'tan gelen fiyatın yazılacağı gizli alan
            'unit_price_at_order': forms.HiddenInput(attrs={'class': 'ordered-unit-price-hidden'}),
        }
    
  
        # 'price', 'subtotal' gibi alanlar view içinde hesaplanacaktır.

  
# 3. KRİTİK EKSİK: FormSet Tanımı
# Bu satır, Order (Ana tablo) ile OrderItem (Detay tablosu) arasındaki ilişkiyi formda kurar.
OrderItemFormSet = inlineformset_factory(
    Order, 
    OrderItem, 
    form=OrderItemForm, 
    extra=1,        # Başlangıçta kaç boş satır gelsin?
    can_delete=True # Satır silme izni



)

class BulkDeliveryForm(forms.Form):
    # KRİTİK: Alanın statik tanımı (Admin'in görmesi için standart kalır)
    courier = forms.ModelChoiceField(
        queryset=Courier.objects.all(),
        required=False,
        label="Teslimatı Yapan Kurye",
        empty_label="Seçim Yok / Admin"
    )
    
    def __init__(self, *args, **kwargs):
        self.deliveries = kwargs.pop('deliveries', None)
        # current_courier parametresini admin action'dan al
        current_courier = kwargs.pop('current_courier', None) 
        super().__init__(*args, **kwargs)
        
        # KRİTİK KONTROL: Eğer kurye tespit edilmişse
        if current_courier:
            # 1. Alanı Gizle: Kurye kullanıcısı için seçim yapmaya gerek yok.
            self.fields['courier'].widget = forms.HiddenInput()
            # 2. Değeri Önceden Ayarla: Form gönderildiğinde bu kuryenin ID'si gidecek.
            self.fields['courier'].initial = current_courier.pk
            # 3. Kurye adını template'te göstermek için bir attribute ekle (opsiyonel ama kullanışlı)
            self.current_courier_name = current_courier.name
            
        # ... (delivery fields döngüsü) ...
        # (Aşağıdaki kısım, dinamik teslimat kalemi alanlarını oluşturur)
        if self.deliveries is not None:
            for delivery in self.deliveries:
                field_name = f'delivered_quantity_{delivery.id}'
                label = f"{delivery.order_item.product.name} ({delivery.order_item.ordered_quantity} Adet Sipariş - Bayi: {delivery.order_item.order.dealer.name})"
                
                self.fields[field_name] = forms.DecimalField(
                    label=label,
                    initial=delivery.delivered_quantity,
                    min_value=0,
                    max_value=delivery.order_item.ordered_quantity 
                )