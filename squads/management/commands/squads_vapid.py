"""Print a VAPID key pair for web push: python manage.py squads_vapid"""
import base64

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Generate VAPID keys for squads web push (set VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY).'

    def handle(self, *args, **options):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec

        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_numbers().private_value.to_bytes(32, 'big')
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b'=').decode()
        self.stdout.write(f'VAPID_PUBLIC_KEY={b64(public)}\nVAPID_PRIVATE_KEY={b64(private)}')
