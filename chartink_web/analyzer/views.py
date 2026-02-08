from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib import messages
from django.urls import reverse
from django.db import models
from django.db.models import Count
from .models import Screener, ScanJob, StockResult
from .services import ChartinkScanner
import threading
import json
import os

def dashboard(request):
    # Get the most recent completed job for stats
    recent_job = ScanJob.objects.filter(status='COMPLETED').order_by('-completed_at').first()
    
    high_conviction_stocks = []
    high_conviction_count = 0
    
    if recent_job:
        # Group by symbol, count occurrences, and order by count descending
        high_conviction_stocks = StockResult.objects.filter(
            job=recent_job
        ).values('symbol').annotate(
            screener_count=Count('screener'),
            close_price=models.Max('close_price'), 
            volume=models.Max('volume')
        ).filter(screener_count__gt=1).order_by('-screener_count')
        
        high_conviction_count = len(high_conviction_stocks)

    context = {
        'recent_job': recent_job,
        'high_conviction_stocks': high_conviction_stocks[:10], # Show top 10 unique ranked
        'high_conviction_count': high_conviction_count
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
    return render(request, 'analyzer/screener_list.html', {'screeners': screeners})

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
    all_stocks = StockResult.objects.filter(job=job).select_related('screener')
    
    # High Conviction (Unique symbols)
    high_conviction_qs = all_stocks.filter(is_high_conviction=True)
    seen = set()
    high_conviction_stocks = []
    for s in high_conviction_qs:
        if s.symbol not in seen:
            high_conviction_stocks.append(s)
            seen.add(s.symbol)
            
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
        
    context = {
        'job': job,
        'all_stocks': all_stocks,
        'high_conviction_stocks': high_conviction_stocks,
        'high_conviction_count': len(high_conviction_stocks),
        'screener_groups': screener_groups,
        'total_count': all_stocks.count()
    }
    return render(request, 'analyzer/result_detail.html', context)
