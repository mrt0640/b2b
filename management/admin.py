from django.contrib.auth.models import User # User modelini import ettiğinizden emin olun.
from datetime import timedelta
from django.conf import settings 
import platform
import pdfkit 
from decimal import Decimal
from .forms import BulkDeliveryForm 
from django import forms
from django.contrib import admin, messages
from django.db.models import Sum, F, DecimalField 
from django.http import HttpResponseRedirect, HttpResponse, FileResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.db import transaction, models 
from django.shortcuts import render, redirect, get_object_or_404 
from django.utils import timezone 
from .views import DeliveryConfirmationView 
from .models import (
    Order, Dealer, OrderItem, Collection, Expense, Product, DealerPrice, 
    RawMaterial, Recipe, RecipeItem, 
    OrderConfiguration, Partner, 
    ProfitDistribution, Courier,
    Delivery, Transaction, 
    Invoice,PartnerProfitShare,
    Unit, ReturnRequest, ReturnRequestItem,
    UnitConversion
    
)
# convert_unit fonksiyonunu models.py'den import ettiğiniz varsayılır.
# Eğer models.py'ye eklediyseniz, bu satırı kullanın:
from .models import convert_unit 

# Hem kendi bilgisayarınızda hem de sunucuda çalışması için:
if platform.system() == "Windows":
    WKHTMLTOPDF_PATH = 'C:/Program Files/wkhtmltopdf/bin/wkhtmltopdf.exe'
else:
    # PythonAnywhere (Linux) üzerindeki yol
    WKHTMLTOPDF_PATH = '/usr/bin/wkhtmltopdf'



def confirm_delivery_action(self, request, queryset):
    # KURYEYİ TESPİT ETME
    current_courier = None
    # Varsayım: Courier modelinde User modeline bağlı bir alan (örneğin 'user') var.
    # Genellikle OneToOneField veya ForeignKey ile bağlanır. 
    if not request.user.is_superuser: # Sadece Admin olmayan kullanıcılar için kontrol et
        try:
        # User objesinden Courier objesini çekmeye çalış
            current_courier = Courier.objects.get(user=request.user) 
        except Courier.DoesNotExist:
        # Eğer giriş yapan kullanıcı bir kurye olarak tanımlı değilse, Admin'dir.
            pass 
        
    # --- Form Görüntüleme (GET) ---
    if 'apply' not in request.POST:
        # Formu sadece seçili olan Delivery nesneleri için başlatmak üzere QuerySet'i hazırlayın
        deliveries_queryset = Delivery.objects.filter(pk__in=queryset.values_list('pk', flat=True))
        
        # KRİTİK DÜZELTME: Formu, tespit edilen kurye ile başlat
        form = BulkDeliveryForm(
            deliveries=deliveries_queryset, 
            current_courier=current_courier # <-- Kurye objesini forma iletiyoruz
        ) 
        
        context = {
            # ... (diğer context verileri) ...
            'form': form,
            'deliveries': deliveries_queryset,
            # ...
        }
        return render(request, 'admin/management/order/bulk_delivery.html', context)

    # --- Form İşleme (POST) ---
    else:
        # ... (POST işlemi kısmı, burada da courier değerini yakalayıp kaydetmelisiniz)
        # Bu kısımda formdan gelen courier ID'sini almalısınız:
        courier_id = request.POST.get('courier')
        if courier_id:
             courier_obj = Courier.objects.get(pk=courier_id)
        else:
             courier_obj = None # Veya None, eğer Admin selection yapmadıysa
        
        # ... (Teslimat kayıtlarını güncellerken courier=courier_obj kullanmayı unutmayın) ...
        pass



# ----------------------------------------------------------------------
# KRİTİK HELPER: TÜRKÇE PARA BİRİMİ FORMATLAMA (1.234,00 TL, Sağa Yaslama)
# ----------------------------------------------------------------------

def format_to_turkish_currency(value, align_right=True, currency_symbol="TL"):
    """
    Değeri Türkçe (1.234,00 TL) formatında ve isteğe bağlı sağa hizalı döndürür.
    """
    if value is None or value == '':
        value = 0.00
    
    try:
        value = float(value) 
        formatted_value = "{:,.2f}".format(value)
        
        # Format: 1,234.56 -> 1.234,56 TL
        if '.' in formatted_value:
            parts = formatted_value.split('.')
            integer_part = parts[0].replace(',', '.') 
            decimal_part = parts[1] 
            turkish_format = f"{integer_part},{decimal_part} {currency_symbol}"
        else:
            turkish_format = f"{formatted_value.replace(',', '.')},00 {currency_symbol}"

    except (TypeError, ValueError):
        turkish_format = f"0,00 {currency_symbol}"

    if align_right:
        return format_html(
            '<span style="text-align: right; display: block; width: 100%; white-space: nowrap;">{}</span>', 
            turkish_format
        )
    return turkish_format 

# ----------------------------------------------------------------------
# 1. GÜVENLİK VE FİLTRELEME MIXIN'İ
# ----------------------------------------------------------------------

class DealerFilteringAdminMixin(admin.ModelAdmin):
    """
    Bayi rolündeki kullanıcıların sadece kendi kayıtlarını görmesini sağlar.
    """
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        
        if request.user.is_superuser:
            return qs

        if not request.user.is_staff:
            return self.model.objects.none()

        try:
            current_dealer = Dealer.objects.get(user=request.user)
            
            if self.model in [Order, Collection, Invoice]: 
                return qs.filter(dealer=current_dealer)
                
            elif self.model is Dealer:
                return qs.filter(id=current_dealer.id) 
                
        except Dealer.DoesNotExist:
            return self.model.objects.none()
        
        return qs 


# ----------------------------------------------------------------------
# 2. ADMIN AKSIYONLARI (ACTION FUNCTIONS)
# ----------------------------------------------------------------------
class OrderItemAdminForm(forms.ModelForm):
    class Meta:
        model = OrderItem
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        if 'unit_price_at_order' in self.fields:
            self.fields['unit_price_at_order'].required = False
        
        if 'product' in self.fields:
            self.fields['product'].queryset = self.fields['product'].queryset.filter(is_active=True)


@admin.action(description="Seçili siparişleri sevkiyata hazırla (TESLİMATTA)")
def send_to_delivery(modeladmin, request, queryset):
    """
    Seçilen siparişler için Delivery kayıtları oluşturur ve sipariş durumunu günceller.
    """
    total_deliveries_created = 0
    
    new_orders = queryset.filter(status='NEW')

    for order in new_orders:
        with transaction.atomic():
            order_items = OrderItem.objects.filter(order=order)
            
            for item in order_items:
                if not Delivery.objects.filter(order_item=item).exists():
                    Delivery.objects.create(
                        order_item=item,
                        delivered_quantity=item.ordered_quantity,
                    )
                    total_deliveries_created += 1
                    
            if total_deliveries_created > 0:
                order.status = 'TESLİMATTA'
                order.save(update_fields=['status'])

    if new_orders.count() == 0:
        modeladmin.message_user(
            request, 
            "Seçilen siparişlerden hiçbiri 'Yeni Sipariş' durumunda değildi. Hiçbir işlem yapılmadı.",
            level='WARNING'
        )
    else:
        modeladmin.message_user(
            request, 
            f"{new_orders.count()} siparişteki toplam {total_deliveries_created} adet sipariş kalemi, sevkiyata hazırlandı."
        )
    return HttpResponseRedirect(request.get_full_path())


# HELPER FUNCTION: Siparişin tüm teslimatlarının onaylanıp onaylanmadığını kontrol eder.
def is_order_fully_delivered(order):
    total_items = OrderItem.objects.filter(order=order).count() 

    if total_items == 0:
        return False
        
    confirmed_deliveries_count = Delivery.objects.filter(
        order_item__order=order,
        is_confirmed=True
    ).count()
    
    return total_items == confirmed_deliveries_count
    


@admin.action(description="Seçili siparişler için Fatura Oluştur")
def generate_invoice(modeladmin, request, queryset):
    """
    CONFIRMED durumundaki siparişler için fatura kaydı oluşturur ve PDF döndürür.
    """
    invoices_created = 0
    invoices_skipped = 0
    
    ready_orders = queryset.filter(status='CONFIRMED', invoice__isnull=True) 
    
    is_single_order = ready_orders.count() == 1
    
    for order in ready_orders:
        if not is_order_fully_delivered(order):
            invoices_skipped += 1
            continue

        try:
            with transaction.atomic():
                
                # Fatura Numarası Oluşturma
                last_invoice = Invoice.objects.all().order_by('-invoice_number').first()
                invoice_num = '100000'
                if last_invoice and last_invoice.invoice_number.isdigit():
                    next_number = int(last_invoice.invoice_number) + 1
                    invoice_num = str(next_number).zfill(6)
                
                # Nihai Tutarı Hesaplama (Transaction'dan)
                delivery_ids = Delivery.objects.filter(
                    order_item__order=order, 
                    is_confirmed=True
                ).values_list('id', flat=True)
                
                final_amount = Transaction.objects.filter(
                    source_model='Delivery',
                    source_id__in=delivery_ids
                ).aggregate(models.Sum('amount'))['amount__sum']
                
                if final_amount is None:
                    final_amount = Decimal('0.00')
                
                # ----------------------------------------------------------------------
                # 1. FATURA SATIR VE KDV DETAY HESAPLAMALARI (Görünüm için)
                # ----------------------------------------------------------------------
                invoice_lines = []
                total_kdv = Decimal('0.00')
                total_vat_excluded = Decimal('0.00') 
                
                deliveries_to_invoice = Delivery.objects.filter(id__in=delivery_ids)
                
                for delivery in deliveries_to_invoice:
                    order_item = delivery.order_item
                    product = order_item.product
                    
                    try:
                        vat_rate_decimal = product.vat_rate if hasattr(product, 'vat_rate') and product.vat_rate else Decimal('0.20') 
                        if vat_rate_decimal > Decimal('1'):
                            vat_rate_decimal = vat_rate_decimal / Decimal('100')
                    except AttributeError:
                        vat_rate_decimal = Decimal('0.20')

                    delivered_qty = Decimal(str(delivery.delivered_quantity))
                    unit_price_at_order = Decimal(str(order_item.unit_price_at_order))
                    
                    vat_factor = Decimal('1') + vat_rate_decimal
                    unit_price_vat_excluded = unit_price_at_order / vat_factor
                    
                    subtotal = unit_price_vat_excluded * delivered_qty
                    vat_amount = subtotal * vat_rate_decimal
                    line_total_vat_included = subtotal + vat_amount
                    
                    total_vat_excluded += subtotal
                    total_kdv += vat_amount
                    
                    invoice_lines.append({
                        'product_name': product.name,
                        'unit': product.unit,
                        'quantity': delivered_qty,
                        'unit_price_vat_excluded': unit_price_vat_excluded,
                        'subtotal': subtotal,
                        'vat_rate': vat_rate_decimal * Decimal('100'), 
                        'vat_amount': vat_amount,
                        'line_total': line_total_vat_included,
                    })

                # ----------------------------------------------------------------------
                # 2. FATURA KAYDINI OLUŞTURMA
                # ----------------------------------------------------------------------
                Invoice.objects.create(
                    order=order,
                    dealer=order.dealer,
                    invoice_number=invoice_num,
                    final_amount=final_amount,
                    invoice_date=timezone.now()
                )
                
                # 3. Sipariş Durumunu Güncelleme
                order.status = 'INVOICED'
                order.save(update_fields=['status'])
                
                invoices_created += 1
                
                # ----------------------------------------------------------------------
                # 4. TEK SİPARİŞ İSE PDF ÇIKTISINI OLUŞTUR VE DÖNDÜR
                # ----------------------------------------------------------------------
                if is_single_order:
                    invoice_data_for_view = {
                        'invoice_number': invoice_num,
                        'invoice_date': timezone.now(),
                        'dealer': order.dealer,
                        'order_id': order.id,
                        'invoice_lines': invoice_lines,
                        'vat_excluded_total': total_vat_excluded, 
                        'total_vat': total_kdv,                   
                        'grand_total': final_amount,              
                    }
                    
                    context = dict(
                        modeladmin.admin_site.each_context(request),
                        invoice=invoice_data_for_view,
                        order=order,
                        title=f"Fatura Detayı: {invoice_num}",
                        is_pdf=True,
                    )

                    html_string = render(request, "admin/management/invoice_view.html", context).content.decode('utf-8')

                    try:
                        config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
                        
                        # KRİTİK: ENCODING VE FONT AYARLARI EKLENDİ (Türkçe karakter çözümü)
                        options = {
                            'encoding': "UTF-8", 
                            'quiet': '', 
                            #'default-font': 'sans-serif' 
                        }
                        
                        pdf_content = pdfkit.from_string(
                            html_string, 
                            False, 
                            configuration=config,
                            options=options
                        ) 

                        pdf_filename = f"FATURA_{invoice_data_for_view['invoice_number']}_{order.dealer.name.replace(' ', '_')}.pdf"

                        response = HttpResponse(pdf_content, content_type='application/pdf')
                        response['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
                        
                        return response 

                    except IOError as e:
                        error_message = f"PDF Oluşturma Hatası: wkhtmltopdf programına erişim sağlanamadı. Lütfen '{WKHTMLTOPDF_PATH}' yolunu kontrol edin. Hata: {e}"
                        modeladmin.message_user(request, error_message, level=messages.ERROR)
                        continue
                        
        except Exception as e:
            modeladmin.message_user(request, f"Hata oluştu: Sipariş #{order.id} - {e}", level=messages.ERROR)            

    if invoices_created > 0:
        modeladmin.message_user(request, f"{invoices_created} adet fatura başarıyla oluşturuldu.", level=messages.SUCCESS)
    if invoices_skipped > 0:
        modeladmin.message_user(request, f"{invoices_skipped} adet sipariş (CONFIRMED durumunda değil veya tam teslimat onaylanmadı) atlandı.", level=messages.WARNING)
    
    return HttpResponseRedirect(request.get_full_path())


# ----------------------------------------------------------------------
# 3. ORDER ADMIN YÖNETİMİ
# ----------------------------------------------------------------------

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    # KRİTİK DÜZELTME: fields listesi güncellendi. ordered_unit eklendi, get_total_price_tl kaldırıldı.
    fields = ('product', 'ordered_quantity', 'ordered_unit', 'get_unit_price_tl', 'get_converted_total_tl') 
    form = OrderItemAdminForm
    can_delete = False
    
    @admin.display(description="Birim Fiyat (Ürün Ana Birimi)")
    def get_unit_price_tl(self, obj):
        price = obj.unit_price_at_order if obj.unit_price_at_order is not None else 0
        return format_to_turkish_currency(price, align_right=False)

    @admin.display(description="Toplam Fiyat (Çevrimli)")
    def get_converted_total_tl(self, obj):
        # Modeldeki get_converted_total metodu kullanılır
        total = obj.get_converted_total() 
        return format_to_turkish_currency(total, align_right=False)
    
    # KRİTİK DÜZELTME: Salt okunur alanlar sadece metotları ve özel durumları içerecek.
    def get_readonly_fields(self, request, obj=None):
        # Salt okunur olması gereken hesaplanmış metotlar:
        fields = ['get_unit_price_tl', 'get_converted_total_tl'] 
        
        if obj and getattr(obj, 'is_locked', False): 
            # Eğer sipariş kilitliyse tüm alanlar salt okunur
            return ('product', 'ordered_quantity', 'ordered_unit', 'get_unit_price_tl', 'get_converted_total_tl') 
        
        # Superuser olmayanlar için varsayılan salt okunur alanlar
        if not request.user.is_superuser:
            return tuple(fields) 
            
        return tuple(fields)
    
    def has_add_permission(self, request, obj=None):
        if obj and getattr(obj, 'is_locked', False):
            return False
        return True
        
    def has_change_permission(self, request, obj=None):
        if obj and getattr(obj, 'is_locked', False):
            return False
        return True


@admin.register(Order)
class OrderAdmin(DealerFilteringAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'dealer', 'order_date', 'get_estimated_total_tl', 'status', 'get_delivery_link', 'get_total_amount', 'status') 
    list_filter = ('status', 'order_date', 'dealer')
    search_fields = ('dealer__name', 'id')
    inlines = [OrderItemInline]
    readonly_fields = ('get_estimated_total_tl', 'get_total_amount') 
    ordering = ('-order_date',)
    
    
    
    @admin.display(description='Toplam Tutar')
    def get_total_amount(self, obj):
        # Order modelindeki @property total_amount'u çağırır
        return f"{obj.total_amount} TL"

    actions = [
        send_to_delivery, generate_invoice, 
        'bulk_delivery_entry',
        'confirm_delivery_action', # Toplu Teslimat Onayı (önceki)
        'confirm_orders_and_deliver_action', # Yeni Sipariş ve Teslimat Onayı
        'imalat_listesi_al'
    ] 
    @admin.action(description='Seçili Siparişleri İmalat Listesine Yazdır')
    def imalat_listesi_al(self, request, queryset):
        # Seçilen siparişlerin ID'lerini alıp URL'e parametre olarak gönderiyoruz
        selected_ids = ",".join([str(q.id) for q in queryset])
        return redirect(f"/management/production-report/pdf/?ids={selected_ids}")
    # Admin listesinin üstüne genel bir buton eklemek isterseniz:
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context['production_button'] = True
        return super().changelist_view(request, extra_context=extra_context)

    # Yeni Action: Siparişi Onayla ve Tüm Teslimatları Yapılmış Olarak İşaretle
    @admin.action(description="Seçilen siparişleri onayla ve teslimatları tamamla (Sistem)")
    def confirm_orders_and_deliver_action(self, request, queryset):
        
        # Action'ı gerçekleştiren Admin/Kullanıcıyı Kurye olarak atamak için
        system_courier = None
        if request.user.is_authenticated:
            try:
                # Eğer oturum açan kullanıcı bir Courier objesine bağlıysa onu çek
                system_courier = Courier.objects.get(user=request.user)
            except Courier.DoesNotExist:
                # Bağlı değilse (Admin sadece sistem işlemi yapıyor), kurye None kalır (Delivery.courier null=True olmalıdır)
                pass 
                
        updated_orders = 0
        updated_deliveries = 0

        with transaction.atomic():
            for order in queryset:
                # Sadece henüz onaylanmamış siparişleri işleyelim
                if order.is_confirmed: # Varsayım: Order modelinde is_confirmed alanı var
                    continue

                # 1. Siparişi Onayla
                order.is_confirmed = True
                order.save() 
                updated_orders += 1

                # 2. İlgili Teslimat Kayıtlarını Güncelle
                
                # Bu siparişe ait OrderItem'ları al
                order_items_qs = OrderItem.objects.filter(order=order)
                
                # OrderItem'lar üzerinden Delivery kayıtlarını bul (henüz teslim edilmemiş olanları)
                for order_item in order_items_qs:
                    delivery_qs = Delivery.objects.filter(
                        order_item=order_item, 
                        is_confirmed=False
                    )
                    
                    if delivery_qs.exists():
                        # Delivery kayıtlarını güncelle:
                        # - delivered_quantity: Sipariş edilen miktarın tamamı (F ile OrderItem'dan çekilir)
                        # - is_confirmed: True
                        # - delivery_date: İşlem anı
                        # - courier: Sistemi kullanan kurye/admin
                        delivery_qs.update(
                            delivered_quantity=F('order_item__ordered_quantity'), 
                            is_confirmed=True,
                            delivery_date=timezone.now(),
                            courier=system_courier # None veya Admin'in Kurye objesi
                        )
                        updated_deliveries += delivery_qs.count()

                
        if updated_orders > 0:
            self.message_user(
                request, 
                f"{updated_orders} adet sipariş onaylandı ve {updated_deliveries} adet teslimat tamamlandı olarak işaretlendi."
            )
        else:
             self.message_user(
                request, 
                "Seçili siparişlerden hiçbiri güncellenmedi veya zaten onaylanmıştı.",
                level=messages.WARNING
            )
        return HttpResponseRedirect(request.get_full_path())





    @admin.display(description="Tahmini Toplam Tutar")
    def get_estimated_total_tl(self, obj):
        value = obj.estimated_total if obj.estimated_total is not None else 0
        return format_to_turkish_currency(value)

    
    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj)) 
        
        if not request.user.is_superuser:
            fields.append('dealer') 
            fields.append('status')
            
        if 'estimated_total' in fields:
            fields.remove('estimated_total')
        fields.append('get_estimated_total_tl')
            
        return tuple(set(fields)) 

    @admin.display(description="Durum / Aksiyon")
    def get_delivery_link(self, obj):
        if obj.status == 'TESLİMATTA': 
            url = reverse('admin:management_delivery_changelist')
            return format_html('<a href="{}?order_item__order__id__exact={}&is_confirmed__exact=0">Teslimatları Gör</a>', url, obj.id)
        
        elif obj.status == 'CONFIRMED':
             return format_html('<span style="color: blue;">Fatura Bekliyor</span>')
        
        elif obj.status == 'INVOICED':
             try:
                 invoice_url = reverse('admin:management_invoice_change', args=(obj.invoice.id,))
                 return format_html('<a href="{}">Fatura {}</a>', invoice_url, obj.invoice.invoice_number)
             except Invoice.DoesNotExist:
                 return format_html('<span style="color: orange;">Faturalandı (Kayıt Yok)</span>')
                 
        return obj.get_status_display()
    
    def check_orders_completion(self, orders_queryset):
        """
        Verilen siparişlerin tüm teslimat kalemlerinin onaylanıp onaylanmadığını kontrol eder 
        ve tamamlandıysa siparişin durumunu günceller.
        """
        completed_orders = 0
        
        for order in orders_queryset:
            # Varsayım: Order modelinde status alanı var (models.py'de kontrol edin).
            if order.status == 'CONFIRMED': 
                continue
                
            # 1. Siparişe ait onaylanmamış (is_confirmed=False) Delivery kayıtlarını say
            unconfirmed_deliveries = Delivery.objects.filter(
                order_item__order=order, 
                is_confirmed=False # Modelinizdeki doğru alan: 'is_confirmed'
            ).count()

            # 2. Kontrol: Eğer onaylanmamış kalem kalmadıysa
            if unconfirmed_deliveries == 0:
                # Siparişin durumunu CONFIRMED olarak güncelle
                order.status = 'CONFIRMED' # Sipariş modelinizin status alanını günceller
                order.save() 
                completed_orders += 1
                
        return completed_orders

    @transaction.atomic
    def bulk_delivery_view(self, request):
        
        order_ids_str = request.GET.get('orders')
        if not order_ids_str:
            self.message_user(request, "Toplu işlem için sipariş seçilmedi.", level='ERROR')
            return redirect('..')
            
        order_ids = [int(i) for i in order_ids_str.split(',') if i.isdigit()]
        
        # KRİTİK DÜZELTME: is_confirmed=False ile filtreleniyor
        deliveries_qs = Delivery.objects.filter(
            order_item__order__id__in=order_ids, 
            is_confirmed=False 
        ).select_related(
            'order_item__order__dealer', 
            'order_item__product'
        )

        if not deliveries_qs.exists():
            self.message_user(request, "Seçilen siparişler için bekleyen bir teslimat kalemi bulunamadı veya hepsi onaylanmış.", level='WARNING')
            return redirect('..')

        if request.method == 'POST':
            
            current_courier = None
            if not request.user.is_superuser:
                 try:
                    current_courier = Courier.objects.get(user=request.user) 
                 except Courier.DoesNotExist:
                    pass

            form = BulkDeliveryForm(
                request.POST, 
                deliveries=deliveries_qs,
                current_courier=current_courier
            )

            if form.is_valid():
                helper = DeliveryConfirmationView()
                updated_count = 0
                orders_to_check_ids = set() # İşlenen siparişlerin ID'lerini tutmak için
                
                # Kurye objesini belirle
                courier_obj = current_courier if current_courier else form.cleaned_data.get('courier')
                
                for delivery in deliveries_qs:
                    
                    delivered_quantity = form.cleaned_data[f'delivered_quantity_{delivery.id}']
                    
                    # 1. TESLİMAT OBJESİNİ GÜNCELLE (HATA DÜZELTİLDİ!)
                    Delivery.objects.filter(pk=delivery.pk).update(
                        delivered_quantity=delivered_quantity,
                        # KRİTİK DÜZELTME: is_confirmed kullanılıyor
                        is_confirmed=True, 
                        delivery_date=timezone.now(),
                        courier=courier_obj, 
                    )
                    
                    # 2. CARİ HESAP İŞLEMİNİ OLUŞTUR (Mevcut Logic)
                    try:
                        qty = Decimal(str(delivered_quantity)) 
                        price = Decimal(str(delivery.order_item.unit_price_at_order)) 
                        # convert_unit fonksiyonunuz models.py'den alınmıştır
                        converted_qty = convert_unit(
                            qty, 
                            delivery.order_item.ordered_unit, 
                            delivery.order_item.product.unit
                        )
                        new_amount = converted_qty * price 

                        # helper.create_debt_transaction metodu
                        helper.create_debt_transaction(delivery.order_item.order.dealer, delivery, new_amount) 
                        
                    except Exception:
                         # Hata yönetimi (loglama yapılabilir)
                         pass


                    updated_count += 1
                    orders_to_check_ids.add(delivery.order_item.order_id) 

                
                # KRİTİK 3. ADIM: SİPARİŞ DURUMUNU KONTROL ET VE ONAYLA
                if orders_to_check_ids:
                    orders_to_check = Order.objects.filter(id__in=orders_to_check_ids)
                    completed_count = self.check_orders_completion(orders_to_check) 
                    
                    if completed_count > 0:
                         self.message_user(request, f"{completed_count} adet sipariş TAMAMLANDI olarak işaretlendi.")

                self.message_user(request, f"{updated_count} adet teslimat kalemi onaylandı.")
                return HttpResponseRedirect(request.get_full_path())
            else:
                 # ... (Hatalı form gönderimi, render etme kısmı) ...
                 pass



        else:
            form = BulkDeliveryForm(deliveries=deliveries_qs)
            
        context = dict(
            self.admin_site.each_context(request),
            title="Toplu Teslimat ve Onay Girişi",
            deliveries=deliveries_qs,
            form=form,
            opts=self.model._meta,
        )
        return render(request, 'admin/management/order/bulk_delivery.html', context)
        
    def save_formset(self, request, form, formset, change):
        current_dealer = form.instance.dealer
        order_instance = form.instance
        
        if not current_dealer and not request.user.is_superuser:
            try:
                current_dealer = Dealer.objects.get(user=request.user)
            except Dealer.DoesNotExist:
                pass

        instances = formset.save(commit=False)
        
        for instance in instances:
            if isinstance(instance, OrderItem):
                
                if instance.product:
                    
                    if instance.pk and instance.unit_price_at_order > 0:
                        continue 
                    
                    final_price = instance.product.price_vat_included
                    if current_dealer:
                        try:
                            special_price_entry = DealerPrice.objects.get(
                                dealer=current_dealer, 
                                product=instance.product
                            )
                            final_price = special_price_entry.price
                        except DealerPrice.DoesNotExist:
                            pass
                    
                    instance.unit_price_at_order = final_price
                
                elif instance.unit_price_at_order is None:
                    instance.unit_price_at_order = Decimal('0.00')
                    
        super().save_formset(request, form, formset, change)
        

        # ------------------------------------------------------------------
        # KRİTİK GÜNCELLEME: Çevrim Fonksiyonu Kullanılarak Toplam Hesaplama
        # ------------------------------------------------------------------
        
        new_estimated_total = Decimal('0.00')
        order_items = OrderItem.objects.filter(order=order_instance).select_related('product')
        
        for item in order_items:
            # Her bir sipariş kaleminin çevrimli toplamını topla
            new_estimated_total += item.get_converted_total() 
        
        order_instance.estimated_total = new_estimated_total
        order_instance.save(update_fields=['estimated_total'])
        
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        if not request.user.is_superuser:
            if 'dealer' in form.base_fields:
                try:
                    current_dealer = Dealer.objects.get(user=request.user)
                    form.base_fields['dealer'].queryset = Dealer.objects.filter(id=current_dealer.id)
                    if obj is None:
                        form.base_fields['dealer'].initial = current_dealer.id
                except Dealer.DoesNotExist:
                    form.base_fields['dealer'].queryset = Dealer.objects.none()

        return form

    def save_model(self, request, obj, form, change):
        if obj.pk is None and not request.user.is_superuser:
            try:
                current_dealer = Dealer.objects.get(user=request.user)
                obj.dealer = current_dealer
            except Dealer.DoesNotExist:
                pass 
        super().save_model(request, obj, form, change)


    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'bulk-delivery/', 
                self.admin_site.admin_view(self.bulk_delivery_view), 
                name='management_order_bulk_delivery'
            ),
        ]
        return custom_urls + urls
    
    @admin.action(description="Seçili siparişler için toplu teslimat/onay girişi")
    def bulk_delivery_entry(self, request, queryset):
        selected_ids = queryset.values_list('id', flat=True)
        selected_ids_str = ','.join(map(str, selected_ids))
        
        return redirect(
            reverse('admin:management_order_bulk_delivery') + f'?orders={selected_ids_str}'
        )

# ----------------------------------------------------------------------
# 4. GLOBAL SİPARİŞ AYARLARI YÖNETİMİ
# ----------------------------------------------------------------------

@admin.register(OrderConfiguration)
class OrderConfigurationAdmin(admin.ModelAdmin):
    list_display = ('is_ordering_enabled',)
    fields = ('is_ordering_enabled',)
    
    def has_add_permission(self, request):
        if self.model.objects.exists():
            return False
        return super().has_add_permission(request)

    def changelist_view(self, request, extra_context=None):
        if self.model.objects.count() == 1:
            obj = self.model.objects.get()
            return HttpResponseRedirect(
                reverse(f'admin:{self.opts.app_label}_{self.opts.model_name}_change', args=(obj.pk,))
            )
        return super().changelist_view(request, extra_context)

    def has_delete_permission(self, request, obj=None):
        return False

# ----------------------------------------------------------------------
# CARİ HAREKETLER (Dealer Admin içinde kullanılacak Inline)
# ----------------------------------------------------------------------
class TransactionInline(admin.TabularInline):
    # Modelin doğru import edildiğinden (models.py'den) emin olun
    model = Transaction 
    fk_name = 'dealer' # Transaction modelindeki Dealer'a işaret eden alan adı
    
    fields = ('transaction_type', 'amount', 'transaction_date', 'get_source_type', 'get_source_id')
    readonly_fields = ('transaction_type', 'amount', 'transaction_date', 'get_source_type', 'get_source_id')
    
    can_delete = False
    extra = 0
    verbose_name = "Cari Hesap Hareketi"
    verbose_name_plural = "Cari Hesap Hareketleri"

    # YENİ METOT: Kaynak model türünü gösterir
    @admin.display(description="Kaynak Türü")
    def get_source_type(self, obj):
        # Generic Foreign Key ile gelen objenin (Örn: Collection, Invoice) adını göster.
        if obj.content_object:
            return obj.content_object.__class__.__name__
        return "Bilinmiyor"

    # YENİ METOT: Kaynak objenin ID'sini gösterir
    @admin.display(description="Kaynak ID")
    def get_source_id(self, obj):
        return obj.source_id



# ----------------------------------------------------------------------
# 4. BAYİ ÖZEL FİYAT YÖNETİMİ
# ----------------------------------------------------------------------

# 1. DealerPrice Inline (Bayinin tüm özel fiyatlarını tek yerde listeler)
class DealerPriceInline(admin.TabularInline):
    model = DealerPrice
    extra = 1
    # Fiyatı formatlı göstermek için mevcut format_to_turkish_currency helper'ını kullanıyoruz
    fields = ('product', 'price', 'get_price_tl') 
    readonly_fields = ('get_price_tl',)
    
    @admin.display(description="Fiyat (TL)")
    def get_price_tl(self, obj):
        # format_to_turkish_currency fonksiyonu zaten admin.py'de tanımlı
        return format_to_turkish_currency(obj.price, align_right=False) 

# 2. Dealer Admin'i Tanımlama/Güncelleme
# Eğer projenizde DealerAdmin tanımlı değilse bu sınıfı ekleyin.
# Eğer tanımlıysa, sadece inlines listesine 'DealerPriceInline' eklediğinizden emin olun.

@admin.register(Dealer)
class DealerAdmin(DealerFilteringAdminMixin, admin.ModelAdmin):
    # Dealer modelindeki alanları listele (models.py'den)
    list_display = ('name', 'tax_id', 'current_balance', 'get_current_balance_tl')
    search_fields = ('name', 'tax_id')
    readonly_fields = ('current_balance', 'get_current_balance_tl',)
    
    # KRİTİK EKLENTİ: DealerPriceInline'ı ekle
    inlines = [TransactionInline]

    # Bakiye alanını formatlı göstermek için
    @admin.display(description="Cari Bakiye")
    def get_current_balance_tl(self, obj):
        # format_to_turkish_currency fonksiyonu zaten admin.py'de tanımlı
        return format_to_turkish_currency(obj.current_balance, align_right=True)

# 3. Tüm özel fiyatları görmek için DealerPriceAdmin (Tüm fiyatları tek bir listede görmek için)
@admin.register(DealerPrice)
class DealerPriceAdmin(admin.ModelAdmin):
    list_display = ('dealer', 'product', 'get_price_tl')
    search_fields = ('dealer__name', 'product__name')
    list_filter = ('dealer', 'product')
    readonly_fields = ('get_price_tl',)
    
    # Fiyatı formatlı göstermek için
    @admin.display(description="Bayiye Özel Satış Fiyatı")
    def get_price_tl(self, obj):
        return format_to_turkish_currency(obj.price, align_right=False)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('name', 'get_amount_tl', 'date')
    list_filter = ('date',)
    
    @admin.display(description="Tutar (TL)")
    def get_amount_tl(self, obj):
        return format_to_turkish_currency(obj.amount)
        
    def has_module_permission(self, request):
        return request.user.is_superuser
        
    def get_queryset(self, request):
        if request.user.is_superuser:
            return super().get_queryset(request)
        return self.model.objects.none() 

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_date', 'dealer', 'transaction_type', 'get_amount_tl', 'source_model', 'source_id')
    list_filter = ('transaction_type', 'dealer', 'transaction_date')
    search_fields = ('dealer__name', 'dealer__tax_id', 'source_model')
    
    @admin.display(description="Tutar (TL)")
    def get_amount_tl(self, obj):
        return format_to_turkish_currency(obj.amount)
    
    def has_module_permission(self, request):
        return request.user.is_superuser
    
    def has_add_permission(self, request):
        return False

# ----------------------------------------------------------------------
# 5. TAHSİLATLAR YÖNETİMİ
# ----------------------------------------------------------------------

@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    # KRİTİK DÜZELTME: Alan adları models.py'dekiyle eşleştirildi.
    list_display = ('id',  'dealer', 'amount', 'created_at') 
    list_filter = ('created_at', 'dealer')                      
    search_fields = ('dealer__name',)
    ordering = ('-created_at',)                                 
    raw_id_fields = ('dealer',) 
    
    # Tahsilat miktarını formatlı gösterelim
    @admin.display(description="Tutar (TL)")
    def get_amount_tl(self, obj):
        # format_to_turkish_currency fonksiyonunun admin.py'de tanımlı olduğunu varsayıyorum
        return format_to_turkish_currency(obj.amount) 

    def save_model(self, request, obj, form, change):
        # Modeldeki save() metodu bakiye güncellemesini yapacaktır.
        # Sadece kaydı tamamlamamız yeterli.
        super().save_model(request, obj, form, change)



# ----------------------------------------------------------------------
# 6. FATURA YÖNETİMİ
# ----------------------------------------------------------------------
# ------------------------------------------------------------------
# YARDIMCI FONKSİYON: Fatura Satırı Hesaplama Mantığı
# (Bu fonksiyonu InvoiceAdmin sınıfının DIŞINA, üstüne ekleyin)
# ------------------------------------------------------------------
def calculate_invoice_lines(deliveries):
    """Teslimatları alır, birim çevrimlerini yaparak fatura satırlarını ve doğru toplamları hesaplar."""
    invoice_lines = []
    total_vat_excluded = Decimal('0.00')
    total_kdv = Decimal('0.00')
    grand_total = Decimal('0.00')

    for delivery in deliveries:
        order_item = delivery.order_item
        product = order_item.product
        
        # ... (KDV, Miktar, Birim kontrolü) ...

        # 3. Fiyat Dönüştürme (KRİTİK HESAPLAMA)
        base_unit_price = Decimal(str(order_item.unit_price_at_order)) # Ürün Ana Birim Fiyatı
        
        # Birim Çevrimi: 1 Sipariş Birimi kaç Ana Birim eder?
        conversion_factor = convert_unit(1, order_item.ordered_unit, product.unit)
        conversion_factor = Decimal(str(conversion_factor))
        if conversion_factor == 0: conversion_factor = Decimal('1.0')
            
        # Faturada görünecek Birim Fiyat (KDV Dahil, Sipariş Birimine Göre)
        display_unit_price_included = base_unit_price * conversion_factor
        
        # KDV Hariç Birim Fiyat
        vat_rate = product.vat_rate / 100 if product.vat_rate else Decimal('0.20')
        vat_factor = Decimal('1') + vat_rate
        display_unit_price_excluded = display_unit_price_included / vat_factor
        
        # 4. Satır Toplamları (KDV Hariç Fiyat * Miktar)
        delivered_qty = Decimal(str(delivery.delivered_quantity))
        line_subtotal = display_unit_price_excluded * delivered_qty
        # Genel Toplamlara Ekle
        total_vat_excluded += line_subtotal
        total_kdv += line_vat_amount
        grand_total += line_total
        
        invoice_lines.append({
            'product_name': product.name,
            'unit': unit_name,
            'quantity': delivered_qty,
            'unit_price': display_unit_price_excluded,
            'subtotal': line_subtotal,
            'vat_rate': vat_rate * 100,
            'vat_amount': line_vat_amount,
            'line_total': line_total,
        })
        
    return invoice_lines, total_vat_excluded, total_kdv, grand_total



@admin.register(Invoice)
class InvoiceAdmin(DealerFilteringAdminMixin, admin.ModelAdmin):
    list_display = ('invoice_number', 'order', 'dealer', 'get_final_amount_tl', 'invoice_date', 'get_pdf_link')
    search_fields = ('invoice_number', 'dealer__name', 'order__id')
    list_filter = ('invoice_date', 'dealer')
    
    readonly_fields = ('invoice_number', 'order', 'dealer', 'final_amount', 'invoice_date', 'get_final_amount_tl')
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:invoice_id>/regenerate-pdf/', 
                self.admin_site.admin_view(self.regenerate_pdf_view), 
                name='management_invoice_regenerate_pdf'
            ),
        ]
        return custom_urls + urls

    def regenerate_pdf_view(self, request, invoice_id, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=invoice_id)
        order = invoice.order
        
        try:
            # 1. Teslimat Verilerini Çek
            # Fatura, onaylanmış teslimatlar üzerinden oluşturulur.
            deliveries = Delivery.objects.filter(order_item__order=order, is_confirmed=True)
            
            # Eğer onaylı teslimat yoksa (örn: test verisi), onaysızları da çekmeyi deneyebiliriz
            # veya boş fatura döner. Test için şunu açabilirsiniz:
            if not deliveries.exists():
                 deliveries = Delivery.objects.filter(order_item__order=order)

            # 2. Verileri Hesapla (Yukarıdaki fonksiyonu çağırıyoruz)
            lines, vat_excluded, total_vat, grand_total = calculate_invoice_lines(deliveries)

            # 3. Görünüm Verisini Hazırla
            invoice_data_for_view = {
                'invoice_number': invoice.invoice_number,
                'invoice_date': invoice.invoice_date,
                'dealer': order.dealer,
                'order_id': order.id,
                'invoice_lines': lines,          # <--- ARTIK DOLU VERİ GİDİYOR
                'vat_excluded_total': vat_excluded, 
                'total_vat': total_vat,         
                'grand_total': grand_total,
            }

            context = dict(
                self.admin_site.each_context(request),
                invoice=invoice_data_for_view,
                order=order,
                title=f"Fatura Detayı: {invoice.invoice_number}",
                is_pdf=True,
            )
            
            html_string = render(request, "admin/management/invoice_view.html", context).content.decode('utf-8')

            config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
            
            # Türkçe karakter desteği için ayarlar
            options = {
                'encoding': "UTF-8", 
                'quiet': '', 
                # 'default-font': 'sans-serif' # Hata verirse bu satırı silin
            }
            
            pdf_content = pdfkit.from_string(
                html_string, 
                False, 
                configuration=config,
                options=options
            ) 

            pdf_filename = f"FATURA_{invoice.invoice_number}_{order.dealer.name.replace(' ', '_')}.pdf"
            response = HttpResponse(pdf_content, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="{pdf_filename}"'
            return response

        except Exception as e:
            self.message_user(request, f"Fatura PDF'i oluşturulurken hata oluştu: {e}", level=messages.ERROR)
            return HttpResponseRedirect(reverse('admin:management_invoice_changelist'))

    @admin.display(description='PDF Aksiyonu')
    def get_pdf_link(self, obj):
        url = reverse('admin:management_invoice_regenerate_pdf', args=[obj.pk]) 
        return format_html(
            '<a class="button" href="{}">PDF İndir</a>',
            url
        )
        
    @admin.display(description="Nihai Tutar (TL)")
    def get_final_amount_tl(self, obj):
        return format_to_turkish_currency(obj.final_amount)
        
    def has_add_permission(self, request):
        return False
        
    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
    

# ------------------------------------------------------------------
# YARDIMCI FONKSİYON: Fatura Satırı Hesaplama Mantığı
# (Kod tekrarını önlemek için bu mantığı bir fonksiyona aldık)
# ------------------------------------------------------------------
def calculate_invoice_lines(deliveries):
    invoice_lines = []
    total_vat_excluded = Decimal('0.00')
    total_kdv = Decimal('0.00')
    grand_total = Decimal('0.00')

    for delivery in deliveries:
        order_item = delivery.order_item
        product = order_item.product
        
        # 1. KDV Oranı
        try:
            vat_rate = product.vat_rate if product.vat_rate else Decimal('0.20')
            if vat_rate > 1: vat_rate = vat_rate / 100
        except:
            vat_rate = Decimal('0.20')

        # 2. Miktar ve Birim
        # Teslim edilen miktar (Örn: 5)
        delivered_qty = Decimal(str(delivery.delivered_quantity))
        
        # Sipariş Birimi (Örn: Koli)
        unit_name = order_item.ordered_unit.name if order_item.ordered_unit else product.unit.name
        
        # 3. Fiyat Dönüştürme (KRİTİK ADIM)
        # Veritabanındaki fiyat (Ana Birim, örn: Adet Fiyatı)
        base_unit_price = Decimal(str(order_item.unit_price_at_order))
        
        # Birim Çevrimi: 1 Sipariş Birimi (Koli) kaç Ana Birim (Adet) eder?
        # Örn: 1 Koli = 10 Adet ise factor = 10
        from .models import convert_unit # convert_unit fonksiyonunu kullanıyoruz
        conversion_factor = convert_unit(1, order_item.ordered_unit, product.unit)
        conversion_factor = Decimal(str(conversion_factor))
        
        # Faturada görünecek Birim Fiyat (KDV Dahil) -> Koli Fiyatı
        display_unit_price_included = base_unit_price * conversion_factor
        
        # KDV Hariç Birim Fiyatı Bulma
        vat_factor = Decimal('1') + vat_rate
        display_unit_price_excluded = display_unit_price_included / vat_factor
        
        # 4. Satır Toplamları
        line_subtotal = display_unit_price_excluded * delivered_qty # KDV Hariç Tutar
        line_vat_amount = line_subtotal * vat_rate # KDV Tutarı
        line_total = line_subtotal + line_vat_amount # KDV Dahil Toplam

        # Genel Toplamlara Ekle
        total_vat_excluded += line_subtotal
        total_kdv += line_vat_amount
        grand_total += line_total
        
        invoice_lines.append({
            'product_name': product.name,
            'unit': unit_name, # <-- YENİ: Birim Adı
            'quantity': delivered_qty,
            'unit_price': display_unit_price_excluded, # Dönüştürülmüş Fiyat
            'subtotal': line_subtotal,
            'vat_rate': vat_rate * 100,
            'vat_amount': line_vat_amount,
            'line_total': line_total,
        })
        
    return invoice_lines, total_vat_excluded, total_kdv, grand_total


# ------------------------------------------------------------------
# AKSİYON: generate_invoice (Güncellenmiş Hali)
# ------------------------------------------------------------------
@admin.action(description="Seçili siparişler için Fatura Oluştur")
def generate_invoice(modeladmin, request, queryset):
    # ... (Başlangıçtaki ready_orders filtreleme kodları aynı) ...
    invoices_created = 0
    invoices_skipped = 0
    ready_orders = queryset.filter(status='CONFIRMED', invoice__isnull=True)
    is_single_order = ready_orders.count() == 1

    for order in ready_orders:
        if not is_order_fully_delivered(order):
            invoices_skipped += 1
            continue

        try:
            with transaction.atomic():
                # ... (Fatura No oluşturma kodları aynı) ...
                last_invoice = Invoice.objects.all().order_by('-invoice_number').first()
                invoice_num = '100000'
                if last_invoice and last_invoice.invoice_number.isdigit():
                    next_number = int(last_invoice.invoice_number) + 1
                    invoice_num = str(next_number).zfill(6)

                # Teslimatları çek
                delivery_ids = Delivery.objects.filter(
                    order_item__order=order, 
                    is_confirmed=True
                ).values_list('id', flat=True)
                deliveries = Delivery.objects.filter(id__in=delivery_ids)

                # --- YENİ HESAPLAMA FONKSİYONUNU ÇAĞIR ---
                lines, vat_excluded, total_vat, grand_total = calculate_invoice_lines(deliveries)
                
                # Fatura Kaydı
                Invoice.objects.create(
                    order=order,
                    dealer=order.dealer,
                    invoice_number=invoice_num,
                    final_amount=grand_total, # Transaction yerine hesaplanan tutarı kullanmak daha güvenli
                    invoice_date=timezone.now()
                )
                
                # Transaction güncelleme (Eğer Transaction modeliniz varsa)
                # Burayı mevcut Transaction mantığınıza göre güncelleyebilirsiniz.
                
                order.status = 'INVOICED'
                order.save(update_fields=['status'])
                invoices_created += 1

                if is_single_order:
                    invoice_data = {
                        'invoice_number': invoice_num,
                        'invoice_date': timezone.now(),
                        'dealer': order.dealer,
                        'order_id': order.id,
                        'invoice_lines': lines, # Hesaplanan satırlar
                        'vat_excluded_total': vat_excluded,
                        'total_vat': total_vat,
                        'grand_total': grand_total,
                    }
                    
                    context = dict(
                        modeladmin.admin_site.each_context(request),
                        invoice=invoice_data,
                        order=order,
                        title=f"Fatura: {invoice_num}",
                        is_pdf=True,
                    )
                    
                    # ... (PDF Oluşturma kodları - encoding options ile birlikte aynı kalacak) ...
                    html_string = render(request, "admin/management/invoice_view.html", context).content.decode('utf-8')
                    config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
                    options = {'encoding': "UTF-8", 'quiet': '', 'default-font': 'sans-serif'}
                    pdf_content = pdfkit.from_string(html_string, False, configuration=config, options=options)
                    
                    response = HttpResponse(pdf_content, content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="FATURA_{invoice_num}.pdf"'
                    return response

        except Exception as e:
            modeladmin.message_user(request, f"Hata: {e}", level=messages.ERROR)

    return HttpResponseRedirect(request.get_full_path())


# ------------------------------------------------------------------
# METOT: InvoiceAdmin.regenerate_pdf_view (Güncellenmiş Hali)
# ------------------------------------------------------------------
# InvoiceAdmin sınıfı içinde regenerate_pdf_view metodunu bununla değiştirin:

    def regenerate_pdf_view(self, request, invoice_id, *args, **kwargs):
        invoice = get_object_or_404(Invoice, pk=invoice_id)
        order = invoice.order
        
        try:
            # Teslimatları bul
            deliveries = Delivery.objects.filter(order_item__order=order, is_confirmed=True)
            
            # --- YENİ HESAPLAMA FONKSİYONUNU ÇAĞIR ---
            # Fatura tekrar oluşturulurken güncel verilerle yeniden hesaplanır
            lines, vat_excluded, total_vat, grand_total = calculate_invoice_lines(deliveries)

            invoice_data = {
                'invoice_number': invoice.invoice_number,
                'invoice_date': invoice.invoice_date,
                'dealer': order.dealer,
                'order_id': order.id,
                'invoice_lines': lines, # Detaylı satırlar
                'vat_excluded_total': vat_excluded,
                'total_vat': total_vat,
                'grand_total': grand_total,
            }

            context = dict(
                self.admin_site.each_context(request),
                invoice=invoice_data,
                order=order,
                title=f"Fatura: {invoice.invoice_number}",
                is_pdf=True,
            )
            
            html_string = render(request, "admin/management/invoice_view.html", context).content.decode('utf-8')
            
            config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
            options = {'encoding': "UTF-8", 'quiet': '', 'default-font': 'sans-serif'}
            
            pdf_content = pdfkit.from_string(html_string, False, configuration=config, options=options) 

            response = HttpResponse(pdf_content, content_type='application/pdf')
            response['Content-Disposition'] = f'attachment; filename="FATURA_{invoice.invoice_number}.pdf"'
            return response

        except Exception as e:
            messages.error(request, f"Hata: {e}")
            return HttpResponseRedirect(reverse('admin:management_invoice_changelist'))


# ----------------------------------------------------------------------
# 7. ORTAKLAR VE KÂR DAĞITIMI
# ----------------------------------------------------------------------

@admin.register(Partner)
class PartnerAdmin(admin.ModelAdmin):
    
    list_display = (
        'get_partner_name', 
        'share_percentage', 
        'total_profit_received', 
        'current_receivable', # <-- BURASI EKLENMELİ/KONTROL EDİLMELİ
        'distribution_ratio', 'id'
    ) 
    list_filter = ('distribution_ratio', 'share_percentage')
    ordering = ('-distribution_ratio', '-share_percentage')
    search_fields = ('user__username', 'user__first_name', 'user__last_name',)
    
    # Ortak adını (User modelindeki bilgiyi) göstermek için yeni bir metot
    def get_partner_name(self, obj):
        # Eğer user atanmışsa tam adını, yoksa kullanıcı adını göster
        if obj.user:
            return obj.user.get_full_name() or obj.user.username
        return "Kullanıcı Atanmamış"
        
    get_partner_name.short_description = "Ortak Adı"

    # Not: Eğer Partner modeline bir is_active/aktif mi alanı eklediyseniz,
    # onu da list_display'e ekleyebilirsiniz.

    @admin.display(description="Mevcut Alacak (TL)")
    def get_current_receivable_tl(self, obj):
        return format_to_turkish_currency(obj.current_receivable)
    
    def has_module_permission(self, request):
        return request.user.is_superuser


    # ***************************************************************
    # KAR DAĞITIM ACTION METODU (GÜNCELLENMİŞ)
    # ***************************************************************
# Aylık karı hesaplayan yardımcı fonksiyon
def calculate_net_profit_for_period(start_date, end_date):
    
    # 1. Toplam Gelirleri Hesapla (Tahsilatlar)
    #Collection: Bayilerden yapılan tahsilatlar
    # Tahsilat (Collection) modelinizde 'amount' alanı olduğunu varsayıyorum.
    collections_sum = Collection.objects.filter(
        collection_date__gte=start_date,  # <-- Düzeltildi
        collection_date__lt=end_date      # <-- Düzeltildi
    ).aggregate(total_sum=Sum('amount'))['total_sum'] or Decimal('0.00')
    
    # 2. Toplam Giderleri Hesapla (Masraflar)
    # Expense: Yapılan masraflar
    # Masraf (Expense) modelinizde 'amount' alanı olduğunu varsayıyorum.
    expenses_sum = Expense.objects.filter(
        date__gte=start_date, 
        date__lt=end_date
    ).aggregate(total_sum=Sum('amount'))['total_sum'] or Decimal('0.00')

    # 3. Net Karı Hesapla
    net_profit = collections_sum - expenses_sum
    
    return net_profit


class PartnerProfitShareInline(admin.TabularInline):
    model = PartnerProfitShare
    extra = 0 # Yeni boş satır gösterme
    can_delete = False
    # total_net_profit hesaplandıktan sonra readonly olmalı
    readonly_fields = ('partner', 'share_ratio', 'calculated_amount')

@admin.register(ProfitDistribution)
class ProfitDistributionAdmin(admin.ModelAdmin):
    list_display = ('month', 'year', 'total_net_profit', 'is_distributed')
    list_filter = ('year', 'month', 'is_distributed')
    ordering = ('-year', '-month')
    search_fields = ('description',)
    
    inlines = [PartnerProfitShareInline] # Inline'ı buraya ekledik
    actions = ['calculate_profit_action', 'distribute_selected_profits_action'] # Yeni Action eklendi
    
    
    # Kullanıcı sadece kârı dağıtıp dağıtmadığını işaretlemeli, kâr otomatik hesaplanmalı
    exclude = ('total_net_profit',) 
    readonly_fields = ('total_net_profit', 'month_start_date', 'month_end_date') # Hesaplanan alanları göster
    
   
    def get_month_dates(self, obj):
        """Ayın başlangıç ve bitiş tarihlerini hesaplar."""
        if not obj.month or not obj.year:
             # Bu durumda bir tuple dönmeli, örn: (None, None)
             return None, None
        
        start_date = timezone.datetime(obj.year, obj.month, 1).date()
        
        if obj.month == 12:
            next_month = 1
            next_year = obj.year + 1
        else:
            next_month = obj.month + 1
            next_year = obj.year
            
        # Bir sonraki ayın ilk gününü bulmak, end date için daha güvenlidir
        next_month_start_date = timezone.datetime(next_year, next_month, 1).date()
        end_date = next_month_start_date - timedelta(days=1)
        
        return start_date, end_date

    def month_start_date(self, obj):
        """Readonly fields için ay başlangıç tarihini döndürür."""
        start_date, _ = self.get_month_dates(obj)
        return start_date.strftime("%d-%m-%Y") if start_date else "N/A"
    month_start_date.short_description = "Başlangıç Tarihi"
    
    def month_end_date(self, obj):
        """Readonly fields için ay bitiş tarihini döndürür."""
        _, end_date = self.get_month_dates(obj)
        return end_date.strftime("%d-%m-%Y") if end_date else "N/A"
    month_end_date.short_description = "Bitiş Tarihi"
    
    # -------------------------------------------------------------
    # KAYIT VE ONAY MANTIĞI
    # -------------------------------------------------------------
    
    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_distributed:
            # Model alanları + kendi metotlarını ekle
            return [f.name for f in self.model._meta.fields] + ['month_start_date', 'month_end_date'] 
        return self.readonly_fields

    def save_model(self, request, obj, form, change):
        if change or not obj.pk:
            start_date, end_date = self.get_month_dates(obj)
            
            # Kârı hesapla (calculate_net_profit_for_period end_date'i dışladığı için +1 gün ekliyoruz)
            calculated_profit = calculate_net_profit_for_period(start_date, end_date + timedelta(days=1)) 
            obj.total_net_profit = calculated_profit
            
        super().save_model(request, obj, form, change)

    @admin.action(description="Seçilen Ay(lar) İçin Kârı Yeniden Hesapla")
    def calculate_profit_action(self, request, queryset):
        # ... (Action kodunun devamı) ...
        
        updated_count = 0
        for obj in queryset:
            start_date, end_date = self.get_month_dates(obj)
            
            # Kârı hesapla (calculate_net_profit_for_period end_date'i dışladığı için +1 gün ekliyoruz)
            calculated_profit = calculate_net_profit_for_period(start_date, end_date + timedelta(days=1))
            
            obj.total_net_profit = calculated_profit
            obj.save(update_fields=['total_net_profit'])
            updated_count += 1
            
        self.message_user(request, f"{updated_count} adet kayıt için kâr başarıyla yeniden hesaplandı.")

    @transaction.atomic # Dağıtımın tek bir işlemde yapılmasını sağlar
    @admin.action(description="Seçilen Ay(lar)daki Kârı Ortaklara Dağıt")
    def distribute_selected_profits_action(self, request, queryset):
        
        # Sadece dağıtılmamış kayıtları işleyelim
        undistributed_queryset = queryset.filter(is_distributed=False)
        
        if not undistributed_queryset.exists():
            self.message_user(request, "Seçilen ayların tamamı zaten dağıtılmış.", level=messages.WARNING)
            return
        
        # Aktif ortakları ve oranlarını bir QuerySet'te çek
        # Partner modelinizde aktiflik alanı varsa, onu da filtreye ekleyin.
        partners = Partner.objects.all().filter(distribution_ratio__gt=0)
        
        if not partners.exists():
            self.message_user(request, "Sistemde dağıtım oranı tanımlanmış aktif ortak bulunamadı.", level=messages.ERROR)
            return

        total_distributed_count = 0
        
        for distribution_record in undistributed_queryset:
            
            total_profit = distribution_record.total_net_profit
            total_ratio = sum([p.distribution_ratio for p in partners])
            
            # Kâr payı dağıtım detaylarını temizle (varsa eski kayıtları sil)
            PartnerProfitShare.objects.filter(distribution=distribution_record).delete()

            # Sadece pozitif kâr varsa dağıtım yap
            if total_profit > Decimal('0.00'):
                
                shares_to_create = []
                
                for partner in partners:
                    ratio = partner.distribution_ratio
                    
                    # Oran (örneğin 30.00) / 100
                    share_multiplier = ratio / Decimal('100.00')
                    
                    calculated_share = total_profit * share_multiplier
                    
                    shares_to_create.append(
                        PartnerProfitShare(
                            distribution=distribution_record,
                            partner=partner,
                            share_ratio=ratio,
                            calculated_amount=calculated_share
                        )
                    )
                
                # Toplu kayıt işlemi
                PartnerProfitShare.objects.bulk_create(shares_to_create)
                
                # Dağıtım tamamlandı olarak işaretle
                distribution_record.is_distributed = True
                distribution_record.save(update_fields=['is_distributed'])
                total_distributed_count += 1
            
            elif total_profit < Decimal('0.00'):
                # Negatif kâr (zarar) durumunda uyarı verebiliriz veya paylaştırmayız
                 self.message_user(request, f"{distribution_record.month}/{distribution_record.year} ayı KÂR yerine ZARAR içerdiği için dağıtım yapılmadı.", level=messages.WARNING)
                 continue


        if total_distributed_count > 0:
            self.message_user(request, f"{total_distributed_count} adet ayın kârı ortaklara başarıyla dağıtıldı.", level=messages.SUCCESS)     



# ----------------------------------------------------------------------
# 8. ÜRÜN VE ENVANTER YÖNETİMİ
# ----------------------------------------------------------------------

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'get_selling_price_tl',
        'unit',
        'price_vat_included', 
        'vat_rate',           
        'get_price_vat_excluded', 
        'is_active'
    ) 
    list_filter = ('is_active', 'unit') 
    search_fields = ('name','unit', 'is_active','price_vat_included', 'vat_rate')

    @admin.display(description="Satış Fiyatı (TL)")
    def get_selling_price_tl(self, obj):
        return format_to_turkish_currency(obj.selling_price)
    
    @admin.display(description="Satış Fiyatı (KDV Hariç)")
    def get_price_vat_excluded(self, obj):
        if obj.price_vat_included and obj.vat_rate is not None:
            try:
                vat_rate_decimal = obj.vat_rate 
                
                if vat_rate_decimal > Decimal('1'):
                    vat_rate_decimal = vat_rate_decimal / Decimal('100')
                    
                vat_factor = Decimal('1') + vat_rate_decimal
                
                price_excluded = obj.price_vat_included / vat_factor
                
                return f"{price_excluded:.2f} TL"
            except Exception:
                return "Hesaplama Hatası"
        return "N/A"

@admin.register(RawMaterial)
class RawMaterialAdmin(admin.ModelAdmin):
    list_display = ('name', 'unit', 'get_cost_price_tl', 'is_active')
    list_filter = ('is_active', 'unit')
    search_fields = ('name',)

    @admin.display(description="Maliyet Fiyatı (TL)")
    def get_cost_price_tl(self, obj):
        return format_to_turkish_currency(obj.cost_price)


class RecipeItemInline(admin.TabularInline):
    model = RecipeItem
    extra = 0
    fields = ('raw_material', 'quantity_required', 'get_unit_display', 'get_cost_display')
    raw_id_fields = ('raw_material',)
    
    # 1. Yeni Görünüm Metodu: JS'in dolduracağı HTML span'ini döndürür
    @admin.display(description="Hammadde Birimi")
    def get_unit_display(self, obj):
        # Eğer kayıtlı bir obje ise veriyi göster, değilse span ID'sini döndür
        unit_name = obj.raw_material.unit.name if obj.raw_material and obj.raw_material.unit else ''
        return format_html(f'<span id="unit-display-{obj.pk if obj.pk else '__prefix__'}">{unit_name}</span>')

    # 2. Yeni Görünüm Metodu: JS'in dolduracağı HTML span'ini döndürür
    @admin.display(description="Birim Maliyeti (TL)")
    def get_cost_display(self, obj):
        cost_price = format_to_turkish_currency(obj.raw_material.cost_price, align_right=False) \
                     if obj.raw_material and obj.raw_material.cost_price is not None else ''
        return format_html(f'<span id="cost-display-{obj.pk if obj.pk else '__prefix__'}">{cost_price}</span>')

    # Salt okunur alanları güncelle
    def get_readonly_fields(self, request, obj=None):
        return ('get_unit_display', 'get_cost_display')
    


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ('product', 'is_active', 'get_total_cost_tl')
    list_filter = ('is_active',)
    search_fields = ('product__name',)
    inlines = [RecipeItemInline]
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'get-raw-material-info/<int:raw_material_id>/', 
                self.admin_site.admin_view(self.get_raw_material_info_ajax_view), 
                name='management_rawmaterial_info' # BU İSİM JS'te kullanılacak
            ),
        ]
        return custom_urls + urls

    class Media:
        js = (
            'admin/js/jquery.init.js', 
            # KRİTİK: Dinleyicimizi admin/js/inlines.js'ten SONRA yüklüyoruz.
            'management/js/recipe_item_inline.js',
        )

    # 2. AJAX View'ı (Hammadde bilgisini JSON olarak döndürür)
    def get_raw_material_info_ajax_view(self, request, raw_material_id):
        from django.http import JsonResponse
        
        try:
            raw_material = RawMaterial.objects.get(pk=raw_material_id)
            
            # Bilgileri formatlı olarak hazırlama
            unit_name = raw_material.unit.name if raw_material.unit else ''
            cost_price = format_to_turkish_currency(raw_material.cost_price, align_right=False)
            
            return JsonResponse({
                'unit_name': unit_name,
                'cost_price_tl': cost_price,
            })
        except RawMaterial.DoesNotExist:
            return JsonResponse({'error': 'Hammadde bulunamadı'}, status=404)
        except Exception:
            return JsonResponse({'error': 'Hata oluştu'}, status=500)
            
    # 3. Custom JavaScript dosyasını yükleme
    class Media:
        js = (
            'admin/js/jquery.init.js', # Django'nun jQuery'sini yükle
            'management/js/recipe_item_inline.js', # Yeni oluşturacağımız dosya
        )



    @admin.display(description="Toplam Hammadde Maliyeti (1 Birim)")
    def get_total_cost_tl(self, obj):
        try: 
            # Yeni hesaplama metodu çağrılıyor
            return format_to_turkish_currency(obj.calculate_total_cost()) 
        except: 
            return format_to_turkish_currency(0)

# ----------------------------------------------------------------------
# 9. KURYE YÖNETİMİ
# ----------------------------------------------------------------------

@admin.register(Courier)
class CourierAdmin(admin.ModelAdmin):
    list_display = ('user', 'name') 
    search_fields = ('user__username', 'name')
    raw_id_fields = ('user',)
    
    def has_module_permission(self, request):
        return request.user.is_superuser

# ----------------------------------------------------------------------
# 10. SEVKİYAT YÖNETİMİ
# ----------------------------------------------------------------------

@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'get_order_id',
        'get_dealer_name',
        'courier', 
        'get_product_name', 
        'get_ordered_quantity', 
        'delivered_quantity', 
        'is_confirmed', 
        'delivery_date'
    )
    list_filter = (
        'is_confirmed',
        'order_item__order__dealer',
        'courier', 
        'order_item__order__id'
    )
    search_fields = (
        'order_item__order__dealer__name', 
        'courier__user__username',
        'order_item__product__name'
    )
    
    raw_id_fields = ('courier', 'order_item') 
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Eğer kullanıcı bir kurye ile ilişkiliyse sadece onun kayıtlarını getir
        return qs.filter(courier__user=request.user)
    
    def get_order_id(self, obj):
        return obj.order_item.order.id
    get_order_id.short_description = 'Sipariş ID'
    
    def get_product_name(self, obj):
        return obj.order_item.product.name
    get_product_name.short_description = 'Ürün'

    def get_ordered_quantity(self, obj):
        return obj.order_item.ordered_quantity
    get_ordered_quantity.short_description = 'Sipariş Miktarı'

    def get_dealer_name(self, obj):
        return obj.order_item.order.dealer.name
    get_dealer_name.short_description = 'Bayi' 

    def has_add_permission(self, request):
        return False
    
    def has_module_permission(self, request):
        return request.user.is_superuser
actions = ['mark_as_delivered']

@admin.action(description='Seçili Teslimatları Onaylandı Olarak İşaretle')
def mark_as_delivered(self, request, queryset):
    updated = queryset.update(is_confirmed=True)
    self.message_user(request, f"{updated} adet teslimat başarıyla onaylandı.")


# ----------------------------------------------------------------------
# 11. BİRİM ÇEVRİM YÖNETİMİ
# ----------------------------------------------------------------------

@admin.register(UnitConversion)
class UnitConversionAdmin(admin.ModelAdmin):
    list_display = ('source_unit', 'target_unit', 'conversion_factor')
    list_filter = ('source_unit', 'target_unit')
    search_fields = ('source_unit__name', 'target_unit__name') # Foreign Key ile arama güncellendi
    ordering = ('source_unit',)
    raw_id_fields = ('source_unit', 'target_unit') # Çok birim olursa kullanışlı olur
# ----------------------------------------------------------------------
# 12. TEMEL BİRİM TANIMLARI YÖNETİMİ (YENİ)
# ----------------------------------------------------------------------

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)
    ordering = ('name',)

class ReturnRequestItemInline(admin.TabularInline):
    model = ReturnRequestItem
    extra = 1
    fields = ('order_item', 'quantity', 'display_return_price')
    readonly_fields = ('display_return_price',)
    
    @admin.display(description='İade Tutarı')
    def display_return_price(self, obj):
        if obj.id:
            return f"{obj.return_price} TL"
        return "0.00 TL"



    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        # Sadece ilgili siparişin ürünlerini getirme mantığı (Öncekiyle aynı)
        object_id = request.resolver_match.kwargs.get('object_id')
        if db_field.name == "order_item" and object_id:
            return_obj = ReturnRequest.objects.get(pk=object_id)
            if return_obj.order:
                kwargs["queryset"] = return_obj.order.items.all()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

@admin.register(ReturnRequest)
class ReturnRequestAdmin(admin.ModelAdmin):
    list_display = ('dealer', 'order', 'amount', 'status')
    readonly_fields = ('amount', 'created_at') # Elle müdahaleyi kapattık
    inlines = [ReturnRequestItemInline]

    def save_related(self, request, form, formsets, change):
        """Ürünler kaydedildikten sonra toplam tutarı zorla hesaplar."""
        super().save_related(request, form, formsets, change)
        
        # 1. Kaydedilen ürünleri taze olarak çek
        instance = form.instance
        # 2. Toplam tutarı yukarıda düzelttiğimiz property üzerinden topla
        total = sum(item.return_price for item in instance.return_items.all())
        
        # 3. Veritabanına doğrudan yaz (update kullanarak save sinyallerini bypass ederiz)
        # Bu işlem, IntegrityError (NOT NULL) hatasını da kesin engeller.
        ReturnRequest.objects.filter(pk=instance.pk).update(amount=total)