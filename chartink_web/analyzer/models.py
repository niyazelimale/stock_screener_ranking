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

class GlobalSettings(models.Model):
    min_ranking_threshold = models.IntegerField(default=2, help_text="Minimum number of screeners for high conviction")
    
    class Meta:
        verbose_name_plural = "Global Settings"

    def __str__(self):
        return "Global Settings"

    @classmethod
    def get_setting(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj

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

class ScanReport(models.Model):
    job = models.OneToOneField(ScanJob, on_delete=models.CASCADE, related_name='report')
    csv_file_path = models.CharField(max_length=500, help_text="Path to the CSV report file")
    created_at = models.DateTimeField(auto_now_add=True)
    total_stocks = models.IntegerField(default=0, help_text="Total number of stocks in this scan")
    high_conviction_count = models.IntegerField(default=0, help_text="Number of high conviction stocks")
    
    class Meta:
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Report for Job {self.job.id} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
