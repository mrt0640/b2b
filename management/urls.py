from django.urls import path, include
from . import views
#from rest_framework.routers import DefaultRouter

# Router tanımı: ViewSet'ler için URL'leri otomatik oluşturur
#router = DefaultRouter()
#router.register(r'expenses', views.ExpenseViewSet, basename='expense')
#router.register(r'collections', views.CollectionViewSet, basename='collection')
#router.register(r'partners', views.PartnerViewSet, basename='partner')
#router.register(r'profit', views.ProfitDistributionViewSet, basename='profit')

app_name = 'management'

urlpatterns = [
     
    path('', views.landing_page_view, name='landing_page'), 
    path('dashboard/', views.dealer_dashboard_view, name='dealer_dashboard'),
    path('siparis/yeni/', views.new_order_view, name='new_order'),
    path('api/product-info/', views.get_product_info, name='product_info_api'),
    path('api/get-product-info/', views.get_product_info, name='get_product_info'),
    path('siparisler/', views.order_list, name='order_list'),
    path('siparis/pdf/<int:pk>/', views.order_pdf, name='order_pdf'),
    

    ]
    # ... (Diğer url patternleriniz buraya gelecek) ...
    # Router tarafından tanımlanan URL'ler (Admin Finansal İşlemler)
    #path('admin/', include(router.urls)),
    #path('production-list/', views.ProductionListView.as_view(), name='production_list'),
    #path('orders/<int:pk>/', views.OrderRetrieveUpdateDestroyAPIView.as_view(), name='order-detail'),
    #path('products/', views.ProductListView.as_view(), name='product-list'), # Ürün Listesi
    #path('balance/', views.DealerBalanceView.as_view(), name='dealer-balance'), # Cari Bakiye
    #path('orders/', views.OrderListCreateAPIView.as_view(), name='order-list-create'),
    #path('deliveries/my-list/', views.CourierDeliveryListView.as_view(), name='courier-delivery-list'), 
    #path('delivery/confirm/<int:delivery_id>/', views.DeliveryConfirmationAPIView.as_view(), name='delivery-confirm'),
    #path('transactions/', views.DealerTransactionListView.as_view(), name='dealer-transactions'),
