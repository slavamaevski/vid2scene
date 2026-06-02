from django.shortcuts import render


def api_docs(request):
    """Main API documentation page."""
    return render(request, 'documentation/api_docs.html')


def getting_started(request):
    """Getting started guide."""
    return render(request, 'documentation/getting_started.html')


def authentication(request):
    """Authentication documentation."""
    return render(request, 'documentation/authentication.html')


def endpoints(request):
    """API endpoints documentation."""
    return render(request, 'documentation/endpoints.html')


def examples(request):
    """Code examples and tutorials."""
    return render(request, 'documentation/examples.html')