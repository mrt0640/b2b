(function($) {
    'use strict';

    function calculateRow($row) {
        var $qtyInput = $row.find('input[name*="quantity"]');
        if ($qtyInput.length === 0) return;

        var qty = parseFloat($qtyInput.val().replace(',', '.')) || 0;
        
        // Fiyatı önce kutudan, kutu yoksa satıra sakladığımız 'data-price' değerinden al
        var $priceInput = $row.find('input[name*="price"]');
        var price = 0;
        
        if ($priceInput.length > 0 && $priceInput.val() !== undefined) {
            price = parseFloat($priceInput.val().replace(',', '.')) || 0;
        } else {
            price = parseFloat($row.attr('data-current-price')) || 0;
        }

        var multiplier = parseFloat($row.attr('data-multiplier')) || 1;
        var total = (qty * price * multiplier).toFixed(2);
        
        // Sonucu ekrana bas
        var $totalCell = $row.find('.my-total-field');
        if ($totalCell.length === 0) {
            $row.append('<td class="my-total-field" style="padding:10px; font-weight:bold; color: #d9534f; text-align:right; width:120px; background: #fff5f5; border: 1px solid #ffeded;">' + total + ' TL</td>');
        } else {
            $totalCell.text(total + " TL");
        }
        
        console.log("HESAPLANDI -> Adet:", qty, "Fiyat:", price, "Toplam:", total);
    }

    $(document).ready(function() {
        console.log("Sistem Aktif: Hafıza Destekli Hesaplama");

        // 1. Miktar değişince hesapla
        $(document).on('input', 'input[name*="quantity"]', function() {
            calculateRow($(this).closest('tr'));
        });

        // 2. Ürün veya Birim değişince AJAX ile fiyatı çek
        $(document).on('change', 'select[name*="product"], select[name*="unit"]', function() {
            var $row = $(this).closest('tr');
            var pId = $row.find('select[name*="product"]').val();
            var uId = $row.find('select[name*="unit"]').val();
            var dId = $('#id_dealer').val();

            if (pId && uId && dId) {
                $.getJSON('/admin/management/order/get-order-price-ajax/', {
                    product_id: pId, unit_id: uId, dealer_id: dId
                }, function(data) {
                    console.log("AJAX'tan gelen fiyat:", data.price);
                    
                    // Fiyatı satırın hafızasına yaz (Kutu olmasa bile kaybolmaz)
                    $row.attr('data-current-price', data.price);
                    $row.attr('data-multiplier', data.multiplier || 1);
                    
                    // Eğer fiyat kutusu varsa ona da yaz
                    var $pInput = $row.find('input[name*="price"]');
                    if ($pInput.length > 0) { $pInput.val(data.price); }

                    calculateRow($row);
                });
            }
        });
    });

})(django.jQuery);