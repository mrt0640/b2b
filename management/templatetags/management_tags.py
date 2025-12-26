from django import template

register = template.Library()

@register.filter
def get_field(form, delivery_id):
    """
    Form içindeki dinamik olarak adlandırılmış bir alanı (field) döndürür.
    
    bulk_delivery_view içinde form alanları şu şekilde adlandırılır:
    'delivered_quantity_<delivery.id>'
    
    Kullanım: {{ form|get_field:delivery.id }}
    """
    field_name = f'delivered_quantity_{delivery_id}'
    try:
        # Form alanını döndür
        return form[field_name]
    except KeyError:
        # Alan bulunamazsa hata yerine None döndür
        return None