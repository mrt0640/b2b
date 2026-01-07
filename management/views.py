from django.template.loader import get_template
from xhtml2pdf import pisa
from io import BytesIO
from django.http import JsonResponse, HttpResponse
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, F, DecimalField 
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework import generics, views, status, viewsets, serializers 
from rest_framework.response import Response
from django.db import transaction 
from django.utils import timezone
from django.utils.decorators import method_decorator
from .permissions import IsDealerUser, IsCourierUser, IsAdminUser, OrderPermissions
from .models import (
    OrderConfiguration, Product, RecipeItem, Dealer, Delivery, OrderItem, Order, 
    Expense, Collection, Partner, ProfitDistribution, Transaction, Courier, DealerPrice 
)
from .serializers import (
    ProductSerializer, DealerSerializer, OrderCreateSerializer,
    OrderSerializer, DeliveryConfirmationSerializer, ExpenseSerializer, 
    CollectionSerializer, PartnerSerializer, ProfitDistributionSerializer,
    ProfitCalculationSerializer, CourierDeliveryListSerializer, TransactionSerializer
)
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages # Kullanıcıya hata mesajı göstermek için
from django.forms import inlineformset_factory # KRİTİK IMPORT
from django.urls import reverse
# messages importu tekrar edilmişti, sadeleştirildi.
from .forms import OrderForm, OrderItemForm, OrderItemFormSet 

# FormSet Tanımlaması
OrderItemFormSet = inlineformset_factory(
    Order, 
    OrderItem, 
    form=OrderItemForm, 
    extra=1, 
    can_delete=True
)

# 1. Yeni Sipariş Kaydı ve Stok Düşme
def new_order(request):
    if request.method == 'POST':
        order_form = OrderForm(request.POST)
        formset = OrderItemFormSet(request.POST,prefix='items')
        
        if order_form.is_valid() and formset.is_valid():
            try:
                # Atomik işlem: Hata olursa hiçbir şey kaydedilmez
                with transaction.atomic():
                    # Sipariş Başlığını Kaydet
                    order = order_form.save(commit=False)
                    # Eğer kullanıcı bir bayiye bağlıysa:
                    # order.dealer = request.user.dealer_profile 
                    order.save()
                    
                    # Sipariş Kalemlerini Kaydet
                    items = formset.save(commit=False)
                    for item in items:
                        item.order = order
                        item.unit_price_at_order = item.product.selling_price
                        item.save()
                        
                        # KRİTİK: Stoktan Düşme İşlemi
                        product = item.product
                        product.current_stock -= item.ordered_quantity
                        product.save()
                
                messages.success(request, f"Sipariş #{order.id} başarıyla oluşturuldu ve stoklar güncellendi.")
                return redirect('management:order_list')
            
            except Exception as e:
                messages.error(request, f"Bir hata oluştu: {str(e)}")
    else:
        order_form = OrderForm()
        formset = OrderItemFormSet()
    
    return render(request, 'management/new_order.html', {
        'order_form': order_form,
        'formset': formset,
        'title': 'Yeni Sipariş Oluştur'
    })




# 2. Sipariş Listeleme (Adım 2)
def order_list(request):
    orders = Order.objects.all().order_by('-order_date') # En yeni en üstte
    return render(request, 'management/order_list.html', {
        'orders': orders,
        'title': 'Siparişlerim'
    })



# 1. LANDING PAGE VIEW
def landing_page_view(request):
    """Projenin ana giriş/karşılama sayfası."""
    # Eğer kullanıcı giriş yapmışsa, onu doğrudan dashboard'a yönlendir
    if request.user.is_authenticated:
        # DÜZELTME: Namespacing (management:) kullanılıyor.
        return redirect('management:dealer_dashboard') 
    
    context = {
        'title': 'Karabulut Ayıntap B2B Sistemi',
    }
    return render(request, 'management/landing_page.html', context)


@login_required 
def dealer_dashboard_view(request):
    """Bayilerin sipariş, cari hesap vb. göreceği ana sayfa."""
    
    context = {
        'user': request.user,
        'welcome_message': f"Hoş geldiniz, {request.user.get_username()}!",
        # Diğer dashboard verileri...
    }
    return render(request, 'management/dashboard.html', context)

@login_required
def new_order_view(request):
    """Bayi için yeni sipariş oluşturma sayfasını gösterir ve işler."""
    
    # 1. Bayiyi bulma
    try:
        dealer = Dealer.objects.get(user=request.user) 
    except Dealer.DoesNotExist:
        messages.error(request, "Sisteme kayıtlı bayi bilginiz bulunamadı.")
        # DÜZELTME: Namespacing ile yönlendirme.
        return redirect('management:landing_page') 

    if request.method == 'POST':
        order_form = OrderForm(request.POST)
        formset = OrderItemFormSet(request.POST, instance=Order()) 
        
       
        if order_form.is_valid() and formset.is_valid():
            with transaction.atomic():
                # 1. Siparişi oluştur (dealer bilgisini ekleyerek)
                order = order_form.save(commit=False)
                order.dealer = dealer
                order.save()
            # 2. Formset verilerini al
            items = formset.save(commit=False)
            total_order_amount = Decimal('0.00')

            for item in items:
                item.order = order
            
                # 3. Bayiye özel fiyat kontrolü
                try:
                    dealer_price_obj = DealerPrice.objects.get(dealer=dealer, product=item.product)
                    price_to_use = dealer_price_obj.price
                except DealerPrice.DoesNotExist:
                    price_to_use = item.product.selling_price
            
                # Birim fiyatı atıyoruz
                item.unit_price_at_order = price_to_use
                item.save()
                
                # 4. Satır toplamını hesapla ve genel toplama ekle
                # get_converted_total metodu unit_price_at_order üzerinden hesaplar
                total_order_amount += item.get_converted_total()

                # 5. Stok güncelleme
                product = item.product
                if hasattr(product, 'current_stock'):
                    product.current_stock -= item.ordered_quantity
                    product.save()

            # --- KRİTİK NOKTA ---
            # 6. Siparişin toplam tutarını veritabanına yazıyoruz
            order.estimated_total = total_order_amount
            order.save() 

            # Formset içindeki silinenleri temizle
            for deleted_obj in formset.deleted_objects:
                deleted_obj.delete()

            messages.success(request, f"Sipariş #{order.pk} başarıyla oluşturuldu. Toplam: {order.estimated_total} TL")
            return redirect(reverse('management:order_list'))
                
                # DÜZELTME: Başarılı siparişten sonra namespacing ile yönlendir.
            return redirect(reverse('management:order_list'))
        else:
            messages.error(request, "Lütfen formdaki hataları düzeltin.")
    else:
        # GET isteğinde, boş formları oluştur
        order_form = OrderForm()
        formset = OrderItemFormSet(instance=Order())

    context = {
        'title': 'Yeni Sipariş Oluştur',
        'order_form': order_form,
        'formset': formset,
    }
    return render(request, 'management/new_order.html', context)

def get_product_info(request):
    product_id = request.GET.get('product_id')
    try:
        product = get_object_or_404(Product, pk=product_id)
        # Mevcut kullanıcıya bağlı bayiyi alıyoruz
        dealer = Dealer.objects.get(user=request.user)
        
        # Bayi fiyatı var mı kontrol et, yoksa ürünün genel satış fiyatını al
        dealer_price_obj = DealerPrice.objects.filter(dealer=dealer, product=product).first()
        price = dealer_price_obj.price if dealer_price_obj else product.selling_price
        
        return JsonResponse({
            'price': float(price),
            'units': [{'id': product.unit.id, 'name': product.unit.name}] if product.unit else []
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)



# ----------------------------------------------------------------------
# HELPER: TÜRKÇE SAYI FORMATLAMA (API İÇİN - Birim/Adet)
# ----------------------------------------------------------------------

def format_to_turkish_number(value):
    """
    Değeri Türkçe sayı (1.234,00) formatında döndürür (API için).
    """
    if value is None or value == '':
        return "0,00"
    
    try:
        value = float(value) 
        formatted_value = "{:,.2f}".format(value)
        
        if '.' in formatted_value:
            parts = formatted_value.split('.')
            integer_part = parts[0].replace(',', '.') 
            decimal_part = parts[1] 
            return f"{integer_part},{decimal_part}"
        else:
            return f"{formatted_value.replace(',', '.')},00"

    except (TypeError, ValueError):
        return "0,00"

# ----------------------------------------------------------------------
# 1. ÜRETİM/DEPO YÖNETİMİ API'LARI
# ----------------------------------------------------------------------

class ProductionItemSerializer(serializers.Serializer):
    """Üretim listesi için geçici serileştirici."""
    product_id = serializers.IntegerField()
    product_name = serializers.CharField(source='product__name')
    # total_quantity ham sayısal değer olarak kaldı
    total_quantity = serializers.DecimalField(max_digits=10, decimal_places=2, source='sum_quantity')
    
    # YENİ ALAN: Formatlanmış miktarı birimle birlikte döndürür
    formatted_quantity = serializers.SerializerMethodField()
    
    def get_formatted_quantity(self, obj):
        quantity = obj.get('sum_quantity')
        unit = obj.get('product__unit_of_measure', '') # Varsayılan boş string
        
        # Miktarı formatla ve birimini ekle
        return f"{format_to_turkish_number(quantity)} {unit}"

    unit_of_measure = serializers.CharField(source='product__unit_of_measure', read_only=True) 

class ProductionListView(views.APIView):
    # ... (Aynı kaldı) ...
    permission_classes = [IsAdminUser] 

    def get(self, request, *args, **kwargs):
        production_list = OrderItem.objects.filter(
            order__status='TESLİMATTA' # 'DELIVERING' yerine 'TESLİMATTA' kullanıldı
        ).values(
            'product__id', 
            'product__name',
            'product__unit_of_measure'
        ).annotate(
            sum_quantity=Sum('ordered_quantity', output_field=DecimalField()) 
        ).order_by('product__name')
        
        serializer = ProductionItemSerializer(production_list, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)
# ----------------------------------------------------------------------
# 2. CARİ HESAP VE TESLİMAT İŞLEMLERİ (CRITICAL)
# ----------------------------------------------------------------------

class DeliveryConfirmationView(views.APIView):
    """
    Kurye'nin teslimatı onayladığı veya Admin'in toplu onaylama aksiyonunun
    çağırdığı helper sınıfı.
    """
    # @transaction.atomic decorator'ı Admin aksiyonunda kullanıldığı için burada opsiyoneldir.
    
    @transaction.atomic 
    def patch(self, request, delivery_id, *args, **kwargs):
        # Kurye yetki kontrolü
        courier_user = request.user
        try:
            courier_profile = Courier.objects.get(user=courier_user)
        except Courier.DoesNotExist:
            raise PermissionDenied("Bu işlem için yetkili Kurye profili bulunamadı.")

        delivery_instance = get_object_or_404(Delivery, id=delivery_id)
        
        # Teslimatın bu kuryeye ait olup olmadığı kontrolü
        if delivery_instance.courier != courier_profile or delivery_instance.is_confirmed:
            raise PermissionDenied("Bu teslimatı onaylama yetkiniz yok veya zaten onaylanmış.")

        serializer = DeliveryConfirmationSerializer(
            instance=delivery_instance, 
            data=request.data, 
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        
        delivered_quantity = serializer.validated_data.get('delivered_quantity', delivery_instance.delivered_quantity)
        
        if delivered_quantity < 0:
             raise ValidationError("Teslim edilen miktar negatif olamaz.")

        # Teslimat kaydını güncelleme
        delivery_instance.delivered_quantity = delivered_quantity
        delivery_instance.is_confirmed = True
        delivery_instance.delivery_date = timezone.now()
        delivery_instance.save() 

        # Cari Hesap Borçlandırma İşlemini Yap
        self.create_debt_transaction(delivery_instance)
        
        return Response(
            {"detail": "Teslimat onaylandı ve bayi cari hesabına borç kaydedildi."}, 
            status=status.HTTP_200_OK
        )

    @transaction.atomic
    def create_debt_transaction(self, delivery_instance):
        """
        HELPER METOT: Borç kaydı oluşturur. Hem Admin aksiyonu hem de API patch 
        metodu tarafından çağrılır.
        """
        ordered_item = delivery_instance.order_item
        dealer = ordered_item.order.dealer
        
        # **KRİTİK:** Önceki borç kaydını sil. Bu, özellikle Admin'in aynı sipariş için
        # toplu girişi tekrar yapabilmesi için önemlidir (re-calculate).
        Transaction.objects.filter(
            source_model='Delivery', 
            source_id=delivery_instance.id, 
            transaction_type='DEBT'
        ).delete()
        
        # Fatura tutarını hesapla
        unit_price = ordered_item.unit_price_at_order
        total_debt_amount = delivery_instance.delivered_quantity * unit_price
        
        if total_debt_amount > 0:
            
            # 1. CARİ HESAP BAKİYESİNİ GÜNCELLE (Borç Ekle)
            dealer.current_balance += total_debt_amount
            dealer.save(update_fields=['current_balance'])
            
            # 2. TRANSACTION (HAREKET) KAYDI OLUŞTUR (Borç)
            Transaction.objects.create(
                dealer=dealer,
                transaction_type='DEBT',
                amount=total_debt_amount,
                source_id=delivery_instance.id,
                source_model='Delivery'
            )
        
        return True 

# ----------------------------------------------------------------------
# 3. KURYEYE AİT TESLİMAT LİSTESİ API'SI
# ----------------------------------------------------------------------

class CourierDeliveryListView(generics.ListAPIView):
    """
    Kuryenin kendisine atanmış ve henüz onaylamadığı teslimatları listeler.
    """
    serializer_class = CourierDeliveryListSerializer
    permission_classes = [IsCourierUser] 

    def get_queryset(self):
        courier_user = self.request.user
        
        try:
            courier_profile = Courier.objects.get(user=courier_user)
            
            return Delivery.objects.filter(
                courier=courier_profile,
                is_confirmed=False 
            ).select_related('order_item__order__dealer', 'order_item__product')
            
        except Courier.DoesNotExist:
            raise PermissionDenied("Bu kullanıcı bir Kurye profiline sahip değil.")

# ----------------------------------------------------------------------
# 4. BAYİ CARİ HAREKET LİSTESİ API'SI
# ----------------------------------------------------------------------
class DealerTransactionListView(generics.ListAPIView):
    """
    Bayinin kendi cari hesap hareketlerini listeler.
    """
    serializer_class = TransactionSerializer
    permission_classes = [IsDealerUser] 
    
    def get_queryset(self):
        try:
            # Django'nun OneToOneField ile otomatik oluşturduğu 'dealer_profile'ı kullanıyoruz
            dealer = self.request.user.dealer_profile
        except Dealer.DoesNotExist:
            raise PermissionDenied("Yetkili bayi hesabı bulunamadı veya yetkisiz erişim.")

        return Transaction.objects.filter(dealer=dealer).order_by('-transaction_date').select_related('dealer')

# ----------------------------------------------------------------------
# 5. SİPARİŞ API VIEWSET'İ
# ----------------------------------------------------------------------

@method_decorator(transaction.atomic, name='dispatch')
class OrderViewSet(viewsets.ModelViewSet):
    """
    Sipariş oluşturma, listeleme, detay görüntüleme ve güncelleme (Bayi ve Admin)
    """
    queryset = Order.objects.all().select_related('dealer').order_by('-order_date')
    permission_classes = [OrderPermissions]

    def get_serializer_class(self):
        if self.action == 'list' or self.action == 'retrieve':
            return OrderSerializer
        elif self.action == 'create':
            return OrderCreateSerializer
        return OrderSerializer 

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        
        if user.is_superuser or (user.is_staff and user.groups.filter(name='Admin').exists()):
            return qs 

        try:
            dealer = Dealer.objects.get(user=user)
            return qs.filter(dealer=dealer)
        except Dealer.DoesNotExist:
            return Order.objects.none()

    def perform_create(self, serializer):
        try:
            dealer = self.request.user.dealer_profile
        except Dealer.DoesNotExist:
            raise PermissionDenied("Sipariş oluşturmak için bir Bayi profili gereklidir.")
            
        if OrderConfiguration.objects.exists() and not OrderConfiguration.objects.first().is_ordering_enabled:
            raise PermissionDenied("Şu anda yeni sipariş alımı kapalıdır.")
        
        serializer.save(dealer=dealer)

# ----------------------------------------------------------------------
# 6. DİĞER API VIEW'LAR
# ----------------------------------------------------------------------

class ProductListView(generics.ListAPIView):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    permission_classes = [IsDealerUser]

def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html  = template.render(context_dict)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result, encoding='utf-8')
    
    options = {
        'encoding': "UTF-8",
        'quiet': '',
    }
    response = HttpResponse(content_type='application/pdf')
    # İndirme ismini belirle
    response['Content-Disposition'] = 'attachment; filename="siparis.pdf"'
    # PDF oluştur
    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
       return HttpResponse('PDF oluşturulurken hata oluştu', status=400)
    return response

# PDF View
def order_pdf(request, pk):
    # .prefetch_related('items') ekleyerek ürünlerin gelmesini garanti ediyoruz
    # Not: Eğer related_name farklıysa 'items' yerine onu yazın
    order = get_object_or_404(Order.objects.prefetch_related('items'), pk=pk)
    context = {'order': order}
    return render_to_pdf('management/order_pdf_template.html', context)

@login_required
def production_pdf_view(request):
    ids = request.GET.get('ids')
    if not ids:
        return HttpResponse("Lütfen sipariş seçin.")

    id_list = ids.split(',')
    
    # 1. Ürün Bazlı Toplamlar (Aynı kalıyor)
    product_totals = OrderItem.objects.filter(order_id__in=id_list).values(
        'product__name'
    ).annotate(
        total_quantity=Sum('ordered_quantity')
    ).order_by('product__name')

    # 2. Hammadde Bazlı Toplamlar (HATA VEREN KISIM BURASIYDI)
    material_totals = RecipeItem.objects.filter(
        recipe__product__orderitem__order_id__in=id_list
    ).values(
        'raw_material__name'
    ).annotate(
        needed_amount=Sum(F('quantity_required') * F('recipe__product__orderitem__ordered_quantity')),
        # Birimi burada 'birim' ismiyle basitçe tanımlıyoruz:
        birim=F('raw_material__unit__name') 
    ).order_by('raw_material__name')

    context = {
        'product_totals': product_totals,
        'material_totals': material_totals,
        'date': timezone.now(),
        'order_count': len(id_list)
    }
    
    return render_to_pdf('management/production_list_pdf.html', context)