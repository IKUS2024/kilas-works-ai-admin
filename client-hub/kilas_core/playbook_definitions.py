"""Closed business workflows and operational vocabulary; no IO or model calls."""
from dataclasses import dataclass
import re

FIELD_LABELS = {
    'service': 'layanan', 'need': 'kebutuhan', 'preferred_date_or_time': 'waktu yang diinginkan',
    'location': 'lokasi', 'item': 'jenis barang', 'weight': 'berat',
    'volume_cbm': 'volume (m³)', 'dimensions': 'ukuran panjang × lebar × tinggi',
    'origin': 'asal', 'destination': 'tujuan', 'transport_preference': 'pilihan pengiriman',
    'items': 'barang/menu', 'quantity': 'jumlah', 'notes': 'catatan',
    'fulfillment': 'cara penerimaan (ambil, antar, atau di tempat)', 'preferred_date': 'tanggal yang diinginkan',
    'preferred_time': 'jam yang diinginkan', 'time_window': 'rentang waktu',
    'requested_service': 'layanan yang dibutuhkan', 'brief': 'kebutuhan proyek',
    'deadline': 'tenggat yang diinginkan', 'budget': 'anggaran yang disampaikan pelanggan',
}


@dataclass(frozen=True)
class Playbook:
    code: str
    label: str
    kind: str
    fields: tuple[str, ...]
    required: tuple[str, ...]
    alternatives: tuple[tuple[str, ...], ...] = ()


PLAYBOOKS = {
    'GENERIC_SERVICE': Playbook('GENERIC_SERVICE', 'Layanan', 'SERVICE',
        ('service', 'need', 'preferred_date_or_time', 'location', 'notes'), ('service', 'need')),
    'LOGISTICS': Playbook('LOGISTICS', 'Pengiriman', 'SHIPMENT',
        ('item', 'weight', 'volume_cbm', 'dimensions', 'origin', 'destination', 'transport_preference', 'notes'),
        ('item', 'weight', 'origin', 'destination'), (('volume_cbm', 'dimensions'),)),
    'SIMPLE_ORDER': Playbook('SIMPLE_ORDER', 'Pesanan', 'ORDER',
        ('items', 'quantity', 'notes', 'fulfillment', 'location'), ('items', 'quantity', 'fulfillment')),
    'BOOKING_SERVICE': Playbook('BOOKING_SERVICE', 'Permintaan booking', 'BOOKING',
        ('service', 'preferred_date', 'preferred_time', 'time_window', 'notes'),
        ('service', 'preferred_date'), (('preferred_time', 'time_window'),)),
    'AGENCY_PROJECT': Playbook('AGENCY_PROJECT', 'Proyek', 'PROJECT',
        ('requested_service', 'brief', 'deadline', 'preferred_date', 'location', 'budget', 'notes'),
        ('requested_service', 'brief')),
}


def select(category):
    """Owner business category is authoritative; no customer/model category override."""
    words = set(re.findall(r'[a-z]+', str(category or '').lower()))
    for code, aliases in (
        ('LOGISTICS', {'logistics', 'logistik', 'freight', 'ekspedisi', 'pengiriman'}),
        ('SIMPLE_ORDER', {'restaurant', 'restoran', 'retail', 'toko', 'warung', 'cafe', 'kafe', 'kuliner', 'food', 'coffee', 'makanan', 'minuman'}),
        ('BOOKING_SERVICE', {'salon', 'appointment', 'spa', 'barbershop', 'klinik', 'clinic'}),
        ('AGENCY_PROJECT', {'agency', 'agensi', 'videography', 'videografi', 'fotografi'}),
    ):
        if words & aliases:
            return PLAYBOOKS[code]
    return PLAYBOOKS['GENERIC_SERVICE']
