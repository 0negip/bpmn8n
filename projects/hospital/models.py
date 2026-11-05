from django.db import models


class DemoSlot(models.Model):
    """Synthetic availability. Replace this adapter with the hospital booking service."""

    service = models.CharField(max_length=100)
    doctor = models.CharField(max_length=100)
    starts_at = models.DateTimeField()
    location = models.CharField(max_length=100)


class DemoBooking(models.Model):
    request_id = models.CharField(max_length=100, unique=True)
    patient_id = models.CharField(max_length=100)
    slot = models.OneToOneField(DemoSlot, on_delete=models.PROTECT)
