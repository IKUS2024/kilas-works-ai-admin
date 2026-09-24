"""Explicit marketplace retirement boundary. Historical schema/services are retained."""
ENDPOINTS = frozenset({
    'products.order_entry', 'products.order_catalog_product', 'products.order_product_image',
    'products.order_whatsapp_handoff', 'products.order_request', 'products.order_requests',
    'products.order_request_search_run', 'products.order_request_detail',
    'admin.order_requests_admin', 'admin.order_catalog_admin', 'admin.order_request_admin_detail',
})


def retired_endpoint(endpoint):
    return endpoint in ENDPOINTS
