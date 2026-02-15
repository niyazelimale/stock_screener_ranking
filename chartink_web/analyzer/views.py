from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.urls import reverse
from django.db import models
from django.db.models import Count
from .models import Screener, ScanJob, StockResult, GlobalSettings, ScanReport
from .services import ChartinkScanner, find_new_stocks
import threading
import json
import os

def dashboard(request):
    # Get the most recent completed job for stats
    recent_job = ScanJob.objects.filter(status='COMPLETED').order_by('-completed_at').first()
    
    settings = GlobalSettings.get_setting()
    threshold = settings.min_ranking_threshold
    
    high_conviction_stocks = []
    high_conviction_count = 0
    
    if recent_job:
        # Group by symbol for high conviction stocks (matching detail page logic)
        high_conviction_stocks = StockResult.objects.filter(
            job=recent_job,
            is_high_conviction=True
        ).values('symbol').annotate(
            screener_count=Count('screener'),
            close_price=models.Max('close_price'), 
            volume=models.Max('volume')
        ).filter(screener_count__gte=threshold).order_by('-screener_count', 'symbol')
        
        high_conviction_count = len(high_conviction_stocks)

    # Get CSV report info if available
    csv_report = None
    if recent_job:
        csv_report = ScanReport.objects.filter(job=recent_job).first()
    
    context = {
        'recent_job': recent_job,
        'high_conviction_stocks': high_conviction_stocks, # Show all unique ranked stocks meeting threshold
        'high_conviction_count': high_conviction_count,
        'threshold': threshold,
        'csv_report': csv_report
    }
    return render(request, 'analyzer/dashboard.html', context)

@require_POST
def start_scan(request):
    if not Screener.objects.filter(is_active=True).exists():
        return JsonResponse({'status': 'error', 'message': 'No active screeners found.'})

    # Create Job
    job = ScanJob.objects.create()
    
    # Start Background Thread
    scanner = ChartinkScanner(job.id)
    thread = threading.Thread(target=scanner.run)
    thread.daemon = True # Daemon thread so it doesn't block server shutdown
    thread.start()
    
    return JsonResponse({'status': 'success', 'job_id': job.id})

def scan_status(request, job_id):
    job = get_object_or_404(ScanJob, id=job_id)
    return JsonResponse({
        'status': job.status,
        'progress': job.progress,
        'log': job.log
    })

def screener_list(request):
    screeners = Screener.objects.all().order_by('-is_active', 'name')
    threshold = GlobalSettings.get_setting().min_ranking_threshold
    return render(request, 'analyzer/screener_list.html', {
        'screeners': screeners,
        'threshold': threshold
    })

def screener_add(request):
    if request.method == 'POST':
        url = request.POST.get('url')
        name = request.POST.get('name')
        if url:
            Screener.objects.create(url=url, name=name)
            messages.success(request, 'Screener added successfully.')
            return redirect('screener_list')
    return render(request, 'analyzer/screener_form.html') # Need to create this simple form

def screener_edit(request, id):
    screener = get_object_or_404(Screener, id=id)
    if request.method == 'POST':
        screener.url = request.POST.get('url')
        screener.name = request.POST.get('name')
        screener.is_active = 'is_active' in request.POST
        screener.save()
        messages.success(request, 'Screener updated successfully.')
        return redirect('screener_list')
    return render(request, 'analyzer/screener_form.html', {'screener': screener})

def screener_delete(request, id):
    screener = get_object_or_404(Screener, id=id)
    screener.delete()
    messages.success(request, 'Screener deleted.')
    return redirect('screener_list')

def screener_import(request):
    # Import from existing JSON config file
    config_path = '/Users/niyazea/Documents/Work/project_v3/screener_config.json'
    try:
        with open(config_path, 'r') as f:
            data = json.load(f)
            urls = data.get('screeners', [])
            count = 0
            for url in urls:
                if not Screener.objects.filter(url=url).exists():
                    # Try to extract a name from URL
                    name = url.split('/')[-1].replace('-', ' ').title()
                    Screener.objects.create(url=url, name=name)
                    count += 1
            if count > 0:
                messages.success(request, f'Successfully imported {count} screeners.')
            else:
                messages.info(request, 'No new screeners to import.')
    except Exception as e:
        messages.error(request, f'Error importing: {str(e)}')
    
    return redirect('screener_list')

def result_detail(request, job_id):
    job = get_object_or_404(ScanJob, id=job_id)
    
    # Calculate screener_count for each symbol
    symbol_counts = StockResult.objects.filter(job=job).values('symbol').annotate(
        screener_count=Count('screener')
    )
    
    # Create a dictionary for quick lookup
    count_map = {item['symbol']: item['screener_count'] for item in symbol_counts}
    
    # Get all stocks and annotate with screener_count
    all_stocks = list(StockResult.objects.filter(job=job).select_related('screener'))
    for stock in all_stocks:
        stock.screener_count = count_map.get(stock.symbol, 1)
    
    # Sort all stocks by screener_count descending
    all_stocks.sort(key=lambda x: x.screener_count, reverse=True)
    
    # High Conviction (Unique symbols, sorted by screener_count)
    settings = GlobalSettings.get_setting()
    threshold = settings.min_ranking_threshold
    
    high_conviction_qs = [s for s in all_stocks if s.screener_count >= threshold]
    seen = set()
    high_conviction_stocks = []
    for s in high_conviction_qs:
        if s.symbol not in seen:
            high_conviction_stocks.append(s)
            seen.add(s.symbol)
    
    # Sort high conviction by screener_count (desc) then symbol (asc)
    high_conviction_stocks.sort(key=lambda x: (-x.screener_count, x.symbol))
            
    # Group by Screener for tabs
    screener_groups = {}
    for stock in all_stocks:
        sid = stock.screener.id
        if sid not in screener_groups:
            screener_groups[sid] = {
                'name': stock.screener.name, 
                'stocks': [],
                'count': 0
            }
        screener_groups[sid]['stocks'].append(stock)
        screener_groups[sid]['count'] += 1
    
    # Sort stocks within each screener group by screener_count
    for sid in screener_groups:
        screener_groups[sid]['stocks'].sort(key=lambda x: x.screener_count, reverse=True)
        
    context = {
        'job': job,
        'all_stocks': all_stocks,
        'high_conviction_stocks': high_conviction_stocks,
        'high_conviction_count': len(high_conviction_stocks),
        'screener_groups': screener_groups,
        'total_count': len(all_stocks)
    }
    return render(request, 'analyzer/result_detail.html', context)
@require_POST
def update_settings(request):
    threshold = request.POST.get('min_ranking_threshold')
    if threshold:
        settings = GlobalSettings.get_setting()
        settings.min_ranking_threshold = int(threshold)
        settings.save()
        messages.success(request, f'Threshold updated to {threshold}.')
    return redirect('screener_list')

def new_stocks_view(request):
    """
    Display stocks that are new in the latest scan compared to a week-old scan.
    """
    # Get the most recent completed job
    recent_job = ScanJob.objects.filter(status='COMPLETED').order_by('-completed_at').first()
    
    if not recent_job:
        context = {
            'error_message': 'No completed scans found. Please run a scan first.'
        }
        return render(request, 'analyzer/new_stocks.html', context)
    
    # Get comparison data
    comparison_data, error = find_new_stocks(recent_job.id)
    
    if error:
        context = {
            'error_message': error,
            'recent_job': recent_job
        }
        return render(request, 'analyzer/new_stocks.html', context)
    
    context = {
        'recent_job': recent_job,
        'new_stocks': comparison_data['new_stocks'],
        'new_count': comparison_data['new_count'],
        'latest_scan_date': comparison_data['latest_scan_date'],
        'comparison_scan_date': comparison_data['comparison_scan_date'],
        'latest_total': comparison_data['latest_total'],
        'old_total': comparison_data['old_total']
    }
    return render(request, 'analyzer/new_stocks.html', context)

def download_csv(request, job_id):
    """
    Download the CSV report for a specific job.
    """
    job = get_object_or_404(ScanJob, id=job_id)
    report = get_object_or_404(ScanReport, job=job)
    
    if not os.path.exists(report.csv_file_path):
        return HttpResponse('CSV file not found.', status=404)
    
    # Serve the file
    response = FileResponse(open(report.csv_file_path, 'rb'), content_type='text/csv')
    filename = os.path.basename(report.csv_file_path)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
