// management/static/management/js/recipe_item_inline.js

(function($) {
    'use strict';

    // Helper: AJAX URL'ini doğru formatla
    function getRawMaterialInfoUrl(rawMaterialId) {
        var currentUrl = window.location.pathname;
        var urlPath = currentUrl.substring(0, currentUrl.indexOf('/management/recipe/')) + 
                      '/management/recipe/get-raw-material-info/' + rawMaterialId + '/';
        return urlPath;
    }

    // AJAX ile Hammadde bilgisini çekme
    function fetchRawMaterialInfo(rawMaterialId, prefix) {
        if (!rawMaterialId) {
            $('#unit-display-' + prefix).text('');
            $('#cost-display-' + prefix).text('');
            return;
        }
        
        var url = getRawMaterialInfoUrl(rawMaterialId);

        $.ajax({
            url: url,
            method: 'GET',
            success: function(data) {
                $('#unit-display-' + prefix).text(data.unit_name || '');
                $('#cost-display-' + prefix).text(data.cost_price_tl || '');
            },
            error: function() {
                $('#unit-display-' + prefix).text('');
                $('#cost-display-' + prefix).text('Hata');
            }
        });
    }

    // Dinleyiciyi Satırlara Bağlama
    function attachListeners(row) {
        // Prefix'i satır ID'sinden veya yeni satır için 'empty'den al
        var prefix = row.attr('id').split('-')[2];
        // Raw ID'nin metin alanını veya gizli inputunu yakala
        var rawMaterialField = $('#id_' + prefix + '-raw_material'); 
        
        // 1. Raw ID metin alanındaki değişiklikleri dinle
        // Kullanıcı ID'yi manuel girerse veya arama penceresi sonucu değiştirirse tetiklenir
        rawMaterialField.on('change', function() {
            fetchRawMaterialInfo($(this).val(), prefix);
        });
        
        // 2. Sayfa yüklendiğinde var olan kayıtlar için bilgiyi çek
        if (rawMaterialField.val()) {
            fetchRawMaterialInfo(rawMaterialField.val(), prefix);
        }
    }

    $(document).ready(function() {
        var inlineGroup = $('#recipeitem_set-group');

        // 1. Mevcut tüm satırlar için dinleyiciyi bağla
        inlineGroup.find('.form-row').each(function() {
             if ($(this).attr('id') && $(this).attr('id').startsWith('recipeitem_set-')) {
                attachListeners($(this));
            }
        });

        // 2. Yeni satır eklendiğinde Django event'ini dinle
        // Bu, Django'nun inlines.js'i ile uyumludur.
        inlineGroup.on('formset:added', function(event, row) {
             // Yeni eklenen satır DOM'a eklendiği anda dinleyiciyi bağla
             attachListeners(row);
        });
    });

})(django.jQuery);