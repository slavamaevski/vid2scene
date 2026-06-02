from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import render
from django.contrib.auth import get_user_model
from django.db.models import Count, Avg
from django.db.models.functions import TruncDate
from video_processor.models import SceneProcessingJob
from datetime import timedelta
from django.utils import timezone
from django.conf import settings

# Create your views here.

@user_passes_test(lambda u: u.is_superuser)
def admin_statistics(request):
    User = get_user_model()
    
    # Get total number of users (excluding superusers + test accounts in production)
    test_accounts = 2 if not settings.DEBUG else 0
    total_users = User.objects.filter(is_superuser=False).count() - test_accounts
    
    # Get active users counts
    seven_days_ago = timezone.now() - timedelta(days=7)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    
    active_users_7d = User.objects.filter(
        is_superuser=False,
        last_login__gte=seven_days_ago
    ).count()
    
    active_users_30d = User.objects.filter(
        is_superuser=False,
        last_login__gte=thirty_days_ago
    ).count()
    
    # Get number of scenes not created by admin (only successful ones)
    scenes_by_others = SceneProcessingJob.objects.exclude(
        user__is_superuser=True
    ).exclude(ply_file='').count()
    
    # Get top 5 users by scene count (only successful ones, excluding superusers)
    scenes_per_user = SceneProcessingJob.objects.exclude(
        ply_file=''
    ).exclude(
        user__is_superuser=True
    ).values(
        'user__username'
    ).annotate(
        scene_count=Count('id')
    ).order_by('-scene_count')[:5]
    
    # Get scene averages
    total_scenes = SceneProcessingJob.objects.exclude(
        ply_file=''
    ).exclude(
        user__isnull=True
    ).exclude(
        user__is_superuser=True
    ).count()
    
    total_non_superusers = User.objects.filter(
        is_superuser=False
    ).count() - test_accounts
    
    users_with_scenes = SceneProcessingJob.objects.exclude(
        ply_file=''
    ).exclude(
        user__isnull=True
    ).exclude(
        user__is_superuser=True
    ).values('user').distinct().count()
    
    avg_scenes_per_user = round(total_scenes / total_non_superusers, 2) if total_non_superusers > 0 else 0
    avg_scenes_per_user_at_least_one = round(total_scenes / users_with_scenes, 2) if users_with_scenes > 0 else 0
    
    # Get scene creation by day (only successful ones, excluding superusers)
    scenes_by_day = SceneProcessingJob.objects.exclude(
        ply_file=''
    ).exclude(
        user__is_superuser=True
    ).annotate(
        date=TruncDate('uploaded_at')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('-date')
    
    # Get number of users with 2+ scenes (only successful ones, excluding superusers)
    users_with_scenes = SceneProcessingJob.objects.exclude(
        ply_file=''
    ).exclude(
        user__is_superuser=True
    ).values(
        'user'
    ).annotate(
        scene_count=Count('id')
    ).filter(scene_count__gte=2).count()
    
    # Get new user signups by day
    signups_by_day = User.objects.filter(
        is_superuser=False
    ).annotate(
        date=TruncDate('date_joined')
    ).values('date').annotate(
        count=Count('id')
    ).order_by('-date')

    # Get scene success rate (excluding superusers)
    total_attempted_scenes = SceneProcessingJob.objects.exclude(
        user__is_superuser=True
    ).count()
    
    successful_scenes = SceneProcessingJob.objects.exclude(
        user__is_superuser=True
    ).exclude(ply_file='').count()
    
    success_rate = round((successful_scenes / total_attempted_scenes * 100), 2) if total_attempted_scenes > 0 else 0

    context = {
        'total_users': total_users,
        'scenes_by_others': scenes_by_others,
        'scenes_per_user': scenes_per_user,
        'scenes_by_day': scenes_by_day,
        'users_with_scenes': users_with_scenes,
        'avg_scenes_per_user': avg_scenes_per_user,
        'avg_scenes_per_user_at_least_one': avg_scenes_per_user_at_least_one,
        'active_users_7d': active_users_7d,
        'active_users_30d': active_users_30d,
        'signups_by_day': signups_by_day,
        'active_user_percentage_7d': round((active_users_7d / total_users * 100), 2) if total_users > 0 else 0,
        'active_user_percentage_30d': round((active_users_30d / total_users * 100), 2) if total_users > 0 else 0,
        'success_rate': success_rate,
    }
    
    return render(request, 'user_statistics/admin_statistics.html', context)
