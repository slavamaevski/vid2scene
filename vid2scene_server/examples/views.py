from django.shortcuts import render
from django.core.cache import cache
from video_processor.models import SceneProcessingJob
from datetime import datetime


def example_list(request):
    """
    Display list of example scenes with caching to improve performance.
    Examples are cached for 1 hour since they change infrequently.
    """
    cache_key = 'examples:list'
    examples = cache.get(cache_key)
    
    if examples is None:
        # Cache miss - fetch from database
        examples = list(SceneProcessingJob.objects.filter(example=True).order_by('-example_sort_order'))
        # Cache for 1 hour (3600 seconds)
        cache.set(cache_key, examples, 3600)
    
    return render(request, "examples/example_list.html", {"examples": examples})


def example_recording(request):
    """
    Renders the Example page with an example YouTube video and corresponding 3D scene.
    """
    current_year = datetime.now().year
    return render(request, 'examples/example_recording.html', {'current_year': current_year})