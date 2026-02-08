from django.db import models
from django.utils import timezone

class Screener(models.Model):
    url = models.URLField(unique=True)
    name = models.CharField(max_length=255, blank=True, help_text="Friendly name for the screener")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name or self.url

class ScanJob(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RUNNING', 'Running'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    progress = models.IntegerField(default=0, help_text="Progress from 0 to 100")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    log = models.TextField(blank=True, help_text="Log output for debugging")

    def __str__(self):
        return f"ScanJob {self.id} - {self.status}"

class StockResult(models.Model):
    job = models.ForeignKey(ScanJob, on_delete=models.CASCADE, related_name='results')
    screener = models.ForeignKey(Screener, on_delete=models.CASCADE, related_name='results')
    symbol = models.CharField(max_length=50)
    name = models.CharField(max_length=255, blank=True)
    nse_code = models.CharField(max_length=50, blank=True, null=True)
    bse_code = models.CharField(max_length=50, blank=True, null=True)
    close_price = models.FloatField(null=True, blank=True)
    volume = models.BigIntegerField(null=True, blank=True)
    is_high_conviction = models.BooleanField(default=False, help_text="True if found in multiple screeners in this job")
    
    def __str__(self):
        return f"{self.symbol} - {self.close_price}"
