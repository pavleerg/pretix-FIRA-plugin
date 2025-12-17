"""
FIRA Plugin for Pretix
Automatically creates fiscalized invoices in FIRA when orders are paid.
"""
from django.dispatch import receiver
from pretix.base.signals import order_paid
from pretix.base.models import LogEntry
import requests
import json
from decouple import config

@receiver(order_paid)
def handle_order_creation(sender, order, **kwargs):
    """
    Signal handler triggered when an order is marked as paid.
    Creates a fiscalized invoice in FIRA with order details.
    """
    # Skip free orders - no invoice needed
    if order.total == 0:
        LogEntry.objects.create(
            content_object=order,
            action_type="FIRA invoice not created - order total is 0",
        )
        print(f"Order {order.code} has total of 0. Skipping FIRA invoice creation.")
        return

    # Group order positions by FIRA product ID
    from collections import defaultdict
    items_grouped = defaultdict(lambda: {"quantity": 0, "price": 0, "name": ""})

    for position in order.positions.all():
        fira_id = position.item.meta_data.get('FIRAID')
        if fira_id and fira_id != '-1':
            items_grouped[fira_id]["quantity"] += 1
            if items_grouped[fira_id]["price"] == 0:
                items_grouped[fira_id]["price"] = float(position.price)
                items_grouped[fira_id]["name"] = str(position.item.internal_name or position.item.name)

    # Build line items for FIRA API
    lineItems = [
        {
            "productCode": fira_id,
            "lineItemId": fira_id,
            "quantity": item_data["quantity"],
            "price": item_data["price"],
            "name": item_data["name"],
            "taxRate": 0.05
        }
        for fira_id, item_data in items_grouped.items()
    ]

    if not lineItems:
        print(f"No valid items with FIRAID for order {order.code}. Skipping FIRA invoice creation.")
        return

    # Configure FIRA API connection
    url = config('FIRA_API_URL', default='https://app.fira.finance/api/v1/webshop/order/custom')
    headers = {
        'FIRA-Api-Key': config('FIRA_API_KEY'),
        'Content-Type': 'application/json'
    }

    # Format datetime for FIRA API (ISO 8601 with Z)
    created_at = order.datetime.strftime('%Y-%m-%dT%H:%M:%SZ')

    # Minimal billing address required by FIRA API
    billing_address = {
        "country": "HR"
    }

    # Calculate invoice totals (prices are tax-included)
    # Formula: netto = brutto / (1 + taxRate), tax = brutto - netto
    total_brutto = 0.0
    total_netto = 0.0
    total_tax = 0.0

    for item in lineItems:
        item_brutto = item["price"] * item["quantity"]
        item_netto = item_brutto / (1 + item["taxRate"])
        item_tax = item_brutto - item_netto
        total_brutto += item_brutto
        total_netto += item_netto
        total_tax += item_tax
    # Round to 2 decimal places
    total_brutto = round(total_brutto, 2)
    total_netto = round(total_netto, 2)
    total_tax = round(total_tax, 2)

    # Prepare invoice data for FIRA
    data = {
        "webshopOrderId": order.id,
        "webshopType": "CUSTOM",
        "webshopOrderNumber": order.code,
        "invoiceType": config('FIRA_INVOICE_TYPE', default='PONUDA'),
        "createdAt": created_at,
        "currency": order.event.currency,
        "paymentType": "KARTICA",
        "taxesIncluded": True,
        "brutto": total_brutto,
        "netto": total_netto,
        "taxValue": total_tax,
        "billingAddress": billing_address,
        "lineItems": lineItems
    }

    print(f"Sending to FIRA: {json.dumps(data, indent=2)}")

    # Send invoice to FIRA API
    try:
        response = requests.post(url, json=data, headers=headers)

        if response.status_code == 200:
            response_data = response.json()
            # Extract invoice details
            invoice_number = response_data.get('invoiceNumber', 'Unknown')
            invoice_first = response_data.get('invoiceFirstNumber', '')
            business_premise = response_data.get('businessPremise', '')
            payment_terminal = response_data.get('paymentTerminal', '')
            jir = response_data.get('jir', 'N/A')

            LogEntry.objects.create(
                content_object=order,
                action_type=f"FIRA fiscalized success, račun number: {invoice_first}-{business_premise}-{payment_terminal}, JIR: {jir}",
            )
            print(f"FIRA invoice created successfully for order {order.code}: {invoice_number}")
        else:
            error_message = f"Status {response.status_code}: {response.text}"
            LogEntry.objects.create(
                content_object=order,
                action_type=f"FIRA invoice creation FAILED. {error_message}",
            )
            print(f"Failed to create FIRA invoice for order {order.code}: {error_message}")
    except Exception as e:
        LogEntry.objects.create(
            content_object=order,
            action_type=f"FIRA invoice creation FAILED with exception: {str(e)}",
        )
        print(f"Exception while creating FIRA invoice for order {order.code}: {str(e)}")
