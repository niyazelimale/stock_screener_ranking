from django.contrib import admin
from .models import Screener, ScanJob, StockResult, GlobalSettings, ScanReport

admin.site.register(Screener)
admin.site.register(ScanJob)
admin.site.register(StockResult)
admin.site.register(GlobalSettings)
admin.site.register(ScanReport)
