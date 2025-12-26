from rest_framework import serializers
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.db.models import Sum, F
from rest_framework.exceptions import ValidationError
from .models import (
    Product, Dealer, DealerPrice, Order, OrderItem, Delivery, 
    Expense, Collection, Partner, ProfitDistribution, Courier, 
    Transaction 
)

# ----------------------------------------------------------------------
# 1. KRİTİK ÖZEL ALAN TANIMI (BAYİ FİYAT HESAPLAMA)
# ----------------------------------------------------------------------

class DealerPriceField(serializers.ReadOnlyField):
    """
    Kullanıcının Bayi tipine göre ürüne ait özel fiyatı veya standart satış fiyatını döndürür.
    """
    def to_representation(self, product):
        request = self.context.get('request')
        final_price = product.selling_price 

        if not request or not request.user.is_authenticated:
            return final_price

        try:
            dealer = request.user.dealer_profile 
        except Dealer.DoesNotExist:
            return final_price

        try:
            dealer_price = DealerPrice.objects.get(dealer=dealer, product=product)
            final_price = dealer_price.price
        except DealerPrice.DoesNotExist:
            pass 

        return final_price

# ----------------------------------------------------------------------
# 2. ÜRÜN VE BAYİ SERİLEŞTİRİCİLERİ
# ----------------------------------------------------------------------

class ProductSerializer(serializers.ModelSerializer):
    bayi_satis_fiyati = DealerPriceField(source='*', read_only=True) 

    class Meta:
        model = Product
        fields = ('id', 'name', 'unit', 'selling_price', 'is_active', 'bayi_satis_fiyati')

class DealerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dealer
        fields = ('id', 'name', 'tax_id', 'current_balance')
        read_only_fields = ('current_balance',)

# ----------------------------------------------------------------------
# 3. SİPARİŞ SERİLEŞTİRİCİLERİ
# ----------------------------------------------------------------------

class OrderItemSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = OrderItem
        fields = ('id', 'product', 'product_name', 'ordered_quantity', 'unit_price_at_order')
        read_only_fields = ('unit_price_at_order',)


class OrderSerializer(serializers.ModelSerializer):
    dealer_name = serializers.CharField(source='dealer.name', read_only=True)
    items = OrderItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Order
        fields = ('id', 'dealer', 'dealer_name', 'order_date', 'estimated_total', 'status', 'status_display', 'items', 'is_locked')
        read_only_fields = ('dealer', 'estimated_total', 'order_date', 'status', 'is_locked')


class OrderCreateSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)

    class Meta:
        model = Order
        fields = ('order_date', 'items')

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop('items')
        
        order = Order.objects.create(**validated_data)
        total_estimated = 0
        
        for item_data in items_data:
            product = item_data['product']
            ordered_quantity = item_data['ordered_quantity']
            
            final_price = product.selling_price
            
            request = self.context.get('request')
            if request and request.user.is_authenticated:
                try:
                    dealer = order.dealer 
                except AttributeError:
                    dealer = get_object_or_404(Dealer, user=request.user)

                try:
                    dealer_price = DealerPrice.objects.get(dealer=dealer, product=product)
                    final_price = dealer_price.price
                except DealerPrice.DoesNotExist:
                    pass

            OrderItem.objects.create(
                order=order,
                product=product,
                ordered_quantity=ordered_quantity,
                unit_price_at_order=final_price 
            )
            
            total_estimated += ordered_quantity * final_price
        
        order.estimated_total = total_estimated
        order.status = 'NEW' 
        order.save()
        
        return order


# ----------------------------------------------------------------------
# 4. FİNANS VE CARİ HESAP SERİLEŞTİRİCİLERİ (EKLENEN KISIM)
# ----------------------------------------------------------------------

class ExpenseSerializer(serializers.ModelSerializer):
    """Giderleri yönetmek için."""
    class Meta:
        model = Expense
        fields = '__all__'
        read_only_fields = ('date',)

class CollectionSerializer(serializers.ModelSerializer):
    """Tahsilatları kaydetmek için."""
    dealer_name = serializers.CharField(source='dealer.name', read_only=True)
    
    class Meta:
        model = Collection
        fields = ('id', 'dealer', 'dealer_name', 'amount', 'collection_date')
        read_only_fields = ('collection_date',)

class PartnerSerializer(serializers.ModelSerializer):
    """Ortaklık bilgilerini yönetmek için."""
    class Meta:
        model = Partner
        fields = '__all__'

class ProfitDistributionSerializer(serializers.ModelSerializer):
    """Kâr dağıtım kayıtlarını görmek için."""
    class Meta:
        model = ProfitDistribution
        fields = '__all__'
        read_only_fields = ('net_profit',)
        
class ProfitCalculationSerializer(serializers.Serializer):
    """API üzerinden kâr hesaplama için kullanılan yardımcı serileştirici."""
    start_date = serializers.DateField(required=True)
    end_date = serializers.DateField(required=True)


class DeliveryConfirmationSerializer(serializers.ModelSerializer):
    """Kuryenin teslim ettiği miktarı girmesi için."""
    class Meta:
        model = Delivery
        fields = ('delivered_quantity',)

class TransactionSerializer(serializers.ModelSerializer):
    """Bayi hareketlerini görüntülemek için (Admin ve Bayi)."""
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    dealer_name = serializers.CharField(source='dealer.name', read_only=True)
    
    class Meta:
        model = Transaction
        fields = (
            'id', 'dealer', 'dealer_name', 'transaction_date', 'transaction_type', 
            'transaction_type_display', 'amount', 'source_model', 'source_id'
        )
        read_only_fields = fields 

class CourierDeliveryListSerializer(serializers.ModelSerializer):
    """Kurye listesi için detaylı serileştirici."""
    order_id = serializers.IntegerField(source='order_item.order.id')
    dealer_name = serializers.CharField(source='order_item.order.dealer.name')
    product_name = serializers.CharField(source='order_item.product.name')
    ordered_quantity = serializers.DecimalField(source='order_item.ordered_quantity', max_digits=10, decimal_places=2)
    
    class Meta:
        model = Delivery
        fields = ('id', 'order_id', 'dealer_name', 'product_name', 'ordered_quantity', 'delivered_quantity')
        read_only_fields = ('delivered_quantity',)